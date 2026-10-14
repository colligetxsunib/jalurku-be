"""Tes minat RIASEC: GET /riasec/questions dan POST /riasec/submit (FR-E2, PRD 8.3).

Membutuhkan PostgreSQL + pgvector (tanda `db`). Memverifikasi penyajian item, skoring
deterministik, penyimpanan ke profil, dan integrasi dengan /explore.
"""

from __future__ import annotations

import pytest

from tests.helpers import masuk

pytestmark = pytest.mark.db

JAWABAN_INVESTIGATIF = {
    "r1": 1, "r2": 1, "r3": 0, "r4": 1,
    "i1": 4, "i2": 4, "i3": 4, "i4": 4,
    "a1": 1, "a2": 0, "a3": 1, "a4": 1,
    "s1": 2, "s2": 2, "s3": 1, "s4": 2,
    "e1": 2, "e2": 2, "e3": 1, "e4": 2,
    "c1": 3, "c2": 3, "c3": 2, "c4": 3,
}


def submit(c, h, jawaban, simpan=True):
    return c.post("/api/v1/riasec/submit", json={"jawaban": jawaban, "simpan": simpan}, headers=h)


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ GET /riasec/questions


def test_questions_publik_dan_lengkap(app_seed, app_config):
    r = app_seed.get("/api/v1/riasec/questions")  # tanpa token: instrumen bersifat publik
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["versi_instrumen"] == app_config.riasec.versi_instrumen
    assert d["dimensi"] == app_config.minat.dimensi
    assert len(d["item"]) == len(app_config.riasec.item)
    assert d["skala"]["min"] == 0 and d["skala"]["maks"] == 4
    # Tiap dimensi minat tertutup oleh minimal satu item (konsistensi instrumen)
    assert {i["dimensi"] for i in d["item"]} == set(app_config.minat.dimensi)
    assert sorted(app_seed.app.openapi()["paths"]["/api/v1/riasec/questions"]) == ["get"]


# ------------------------------------------------------------------ POST /riasec/submit


def test_submit_wajib_token(app_seed):
    assert app_seed.post("/api/v1/riasec/submit", json={"jawaban": {"r1": 4}}).status_code == 401


def test_submit_menghasilkan_vektor_dan_holland_code(app_seed, app_config):
    h = masuk(app_seed)
    d = ok(submit(app_seed, h, JAWABAN_INVESTIGATIF))
    assert d["skor_norm"]["investigatif"] == 1.0  # semua item I dijawab maksimum
    assert d["dimensi_teratas"][0] == "investigatif"
    assert d["holland_code"].startswith("I")
    assert set(d["skor_norm"]) == set(app_config.minat.dimensi)
    assert d["terjawab"] == len(JAWABAN_INVESTIGATIF) and d["tersimpan"] is True
    assert "indikatif" in d["catatan"]


def test_submit_deterministik(app_seed):
    h = masuk(app_seed)
    a = ok(submit(app_seed, h, JAWABAN_INVESTIGATIF, simpan=False))
    b = ok(submit(app_seed, h, JAWABAN_INVESTIGATIF, simpan=False))
    assert a["skor_norm"] == b["skor_norm"] and a["holland_code"] == b["holland_code"]


def test_simpan_menulis_vektor_minat_ke_profil(app_seed):
    h = masuk(app_seed)
    d = ok(submit(app_seed, h, JAWABAN_INVESTIGATIF, simpan=True))
    profil = app_seed.get("/api/v1/profile", headers=h).json()["profil"]
    # Vektor minat tersimpan utuh di profil (termasuk dimensi bernilai > 0 pada data ini).
    for dim, nilai in d["skor_norm"].items():
        if nilai > 0:
            assert profil["minat"][dim] == nilai
    # Minat kini mengalir ke /explore (konsumen vektor yang sama).
    rek = app_seed.post("/api/v1/explore", json={"top_n": 5}, headers=h).json()["rekomendasi"]
    assert rek and rek[0]["skor_kecocokan"] >= rek[-1]["skor_kecocokan"]


def test_pratinjau_tanpa_simpan_tidak_mengubah_profil(app_seed):
    h = masuk(app_seed)
    ok(submit(app_seed, h, JAWABAN_INVESTIGATIF, simpan=False))
    assert app_seed.get("/api/v1/profile", headers=h).json()["profil"]["minat"] is None


def test_submit_parsial_boleh(app_seed):
    h = masuk(app_seed)
    d = ok(submit(app_seed, h, {"i1": 4, "i2": 4}))
    assert d["skor_norm"]["investigatif"] == 1.0 and d["terjawab"] == 2


# ------------------------------------------------------------------ validasi (422)


def test_validasi_id_tak_dikenal_dan_nilai_di_luar_skala(app_seed):
    h = masuk(app_seed)
    r = submit(app_seed, h, {"tidak_ada": 2})
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"][0]["field"] == "jawaban"
    r = submit(app_seed, h, {"i1": 9})
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"][0]["field"] == "jawaban"


def test_validasi_badan_salah(app_seed):
    h = masuk(app_seed)
    for salah in ({"jawaban": {}}, {"jawaban": {"i1": 1}, "lain": 1}, {}, {"jawaban": {"I1": 1}}):
        assert app_seed.post("/api/v1/riasec/submit", json=salah, headers=h).status_code == 422, salah
