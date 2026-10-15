"""Tes minat RIASEC: kontrak dengan dashboard, skoring, cek kualitas, pemetaan ke profil, /explore."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, AppConfig, ConfigError, load_app_config
from app.domain import riasec as domain
from app.ingest.service import ingest_direktori
from app.main import create_app
from app.services.riasec import muat_instrumen, parse_instrumen
from tests.conftest import make_settings
from tests.helpers import SEED_DIR, masuk, muat_persona

DIM = ["realistis", "investigatif", "artistik", "sosial", "enterprising", "konvensional"]
SKALA = {"min": 1, "maks": 5, "label": {"1": "Sangat tidak suka", "5": "Sangat suka"}}
RIASEC_DIR = ROOT_DIR / "data" / "riasec"  # data/riasec repo (instrumen asli)
SUMBER_V1 = (
    "Disusun tim berdasarkan kerangka teori Holland (RIASEC). Butir orisinal, "
    "belum divalidasi psikometrik, bukan tes psikologi."
)
TERLARANG = re.compile(r"(?i)\bO\*?NET\b|domain publik|public domain")


def tulis_instrumen(folder: Path, per_dimensi: int = 4, **ubah) -> Path:
    data = {
        "versi_instrumen": "uji-v1",
        "sumber": "instrumen uji (bukan instrumen sungguhan)",
        "skala": SKALA,
        "dimensi": DIM,
        "item": [
            {"id": f"{d[:3]}-{n}", "teks": f"Butir uji {d} {n}", "dimensi": d}
            for d in DIM
            for n in range(1, per_dimensi + 1)
        ],
        **ubah,
    }
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "instrumen_v1.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def jawab(per_dim: dict[str, list[int]]) -> dict[str, int]:
    return {f"{d[:3]}-{n}": v for d, vs in per_dim.items() for n, v in enumerate(vs, start=1)}


SEHAT = jawab(
    {
        "realistis": [5, 5, 4, 5],
        "investigatif": [4, 5, 4, 4],
        "artistik": [2, 3, 2, 3],
        "sosial": [3, 2, 3, 3],
        "enterprising": [1, 2, 1, 2],
        "konvensional": [3, 4, 3, 3],
    }
)
SKOR_SEHAT = {
    "realistis": 0.9375,
    "investigatif": 0.8125,
    "artistik": 0.375,
    "sosial": 0.4375,
    "enterprising": 0.125,
    "konvensional": 0.5625,
}


@pytest.fixture()
def app_riasec(clean_db: Engine, app_config: AppConfig, tmp_path: Path):
    """Aplikasi ter-seed dengan instrumen uji (bukan contoh): 4 butir per dimensi."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    tulis_instrumen(tmp_path / "riasec")
    app = create_app(make_settings(riasec_dir=str(tmp_path / "riasec")), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def app_contoh(clean_db: Engine, app_config: AppConfig, tmp_path: Path):
    """Aplikasi ter-seed dengan folder yang HANYA berisi instrumen_contoh.json (fixture)."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    folder = tmp_path / "riasec"
    folder.mkdir()
    shutil.copy(RIASEC_DIR / "instrumen_contoh.json", folder / "instrumen_contoh.json")
    app = create_app(make_settings(riasec_dir=str(folder)), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def kirim(c, h, jawaban, simpan=True):
    return c.post("/api/v1/riasec/submit", json={"jawaban": jawaban, "simpan": simpan}, headers=h)


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def hitung_baris(engine: Engine, tabel: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {tabel}")).scalar_one()


# ------------------------------------------------------------------ kontrak


@pytest.mark.db
def test_questions_publik_dan_sesuai_kontrak_dashboard(app_riasec):
    r = app_riasec.get("/api/v1/riasec/questions")  # tanpa token
    d = ok(r)
    assert set(d) >= {"versi_instrumen", "sumber", "skala", "dimensi", "item", "pernyataan"}
    assert d["versi_instrumen"] == "uji-v1" and d["instrumen_contoh"] is False
    assert d["skala"] == {"min": 1, "maks": 5, "label": SKALA["label"]}
    assert d["dimensi"] == DIM and len(d["item"]) == 24
    assert set(d["item"][0]) == {"id", "teks", "dimensi"}
    assert "bukan tes psikologi" in d["pernyataan"].lower()


@pytest.mark.db
def test_submit_wajib_token_dan_metode(app_riasec):
    assert app_riasec.post("/api/v1/riasec/submit", json={"jawaban": {}}).status_code == 401
    paths = app_riasec.app.openapi()["paths"]
    assert sorted(paths["/api/v1/riasec/questions"]) == ["get"]
    assert sorted(paths["/api/v1/riasec/submit"]) == ["post"]


@pytest.mark.db
def test_berkas_contoh_dipakai_bila_instrumen_v1_belum_ada(app_contoh):
    d = ok(app_contoh.get("/api/v1/riasec/questions"))
    assert d["instrumen_contoh"] is True and d["sumber"] == "contoh, bukan instrumen"
    assert len(d["item"]) == 12 and all("CONTOH" in b["teks"] for b in d["item"])  # 2 per dimensi
    assert d["dimensi"] == DIM


@pytest.mark.db
def test_instrumen_v1_asli_memenuhi_spesifikasi(app_seed, app_config):
    """data/riasec/instrumen_v1.json: 36 butir orisinal, 6 per dimensi, skala 0..4."""
    r = app_seed.get("/api/v1/riasec/questions")  # tanpa token
    d = ok(r)
    assert d["versi_instrumen"] == "riasec-id-v1"
    assert d["instrumen_contoh"] is False  # bukan berkas contoh
    assert d["sumber"] == SUMBER_V1
    assert (d["skala"]["min"], d["skala"]["maks"]) == (0, 4)
    assert set(d["skala"]["label"]) == {"0", "1", "2", "3", "4"}  # tiap nilai berlabel
    assert d["min_terjawab"] == app_config.riasec.min_terjawab_per_dimensi  # aditif, dari config
    assert len(d["item"]) == 36
    per_dimensi = {dim: [b for b in d["item"] if b["dimensi"] == dim] for dim in DIM}
    assert set(per_dimensi) == set(DIM) and all(len(v) == 6 for v in per_dimensi.values())
    ids = [b["id"] for b in d["item"]]
    assert len(set(ids)) == 36  # id unik
    assert all(re.match(r"^[a-z][a-z0-9_-]*$", i) for i in ids)
    teks = [b["teks"] for b in d["item"]]
    assert len(set(teks)) == 36 and all(t and t.endswith(".") for t in teks)  # teks unik, kalimat
    assert all(len(t) <= 100 for t in teks)  # satu kalimat pendek
    assert not TERLARANG.search(json.dumps(d))  # tidak ada klaim sumber lain
    # submit penuh atas instrumen asli: 200 dan tidak perlu berkas contoh
    d2 = ok(kirim(app_seed, masuk(app_seed), {b["id"]: 2 for b in d["item"]}, simpan=False))
    assert d2["versi_instrumen"] == "riasec-id-v1" and d2["instrumen_contoh"] is False
    assert not TERLARANG.search(json.dumps(d2))
    assert "contoh" not in d2["pernyataan"].lower() and "contoh" not in d2["catatan"].lower()


# ------------------------------------------------------------------ skoring


@pytest.mark.db
def test_skor_dinormalisasi_0_sampai_1_dan_holland_code(app_riasec):
    h = masuk(app_riasec)
    d = ok(kirim(app_riasec, h, SEHAT))
    assert d["skor_norm"] == SKOR_SEHAT
    assert all(0 <= v <= 1 for v in d["skor_norm"].values())
    assert d["dimensi_teratas"] == ["realistis", "investigatif", "konvensional"]
    assert d["holland_code"] == "RIC"
    assert (d["terjawab"], d["total_item"]) == (24, 24)
    assert d["dimensi_tidak_dihitung"] == [] and d["tersimpan"] is True
    assert d["keyakinan"] == "sedang" and d["alasan_keyakinan"] == []


@pytest.mark.db
def test_pernyataan_bukan_tes_psikologi_ada_di_setiap_hasil(app_riasec):
    d = ok(kirim(app_riasec, masuk(app_riasec), SEHAT, simpan=False))
    assert "bukan tes psikologi dan bukan diagnosis" in d["pernyataan"].lower()
    assert d["pernyataan"] in d["catatan"]


@pytest.mark.db
def test_skor_seri_diurutkan_deterministik_menurut_urutan_dimensi(app_riasec):
    seri = jawab({d: [4, 4, 4, 4] for d in DIM[:3]} | {d: [2, 2, 2, 2] for d in DIM[3:]})
    d = ok(kirim(app_riasec, masuk(app_riasec), seri, simpan=False))
    assert d["holland_code"] == "RIA"


@pytest.mark.db
def test_jawaban_parsial_dimensi_kurang_terjawab_tidak_dihitung(app_riasec):
    h = masuk(app_riasec)
    parsial = {k: v for k, v in SEHAT.items() if k.startswith(("rea", "inv"))}
    parsial["art-1"] = 5  # satu butir saja: di bawah min_terjawab_per_dimensi (2)
    d = ok(kirim(app_riasec, h, parsial))
    assert set(d["skor_norm"]) == {"realistis", "investigatif"}  # bukan dianggap nol
    assert d["dimensi_tidak_dihitung"] == ["artistik", "sosial", "enterprising", "konvensional"]
    assert d["holland_code"] == "RI" and d["terjawab"] == 9
    assert d["terjawab_per_dimensi"]["artistik"] == 1


@pytest.mark.db
def test_jawaban_kosong_tidak_menghitung_dan_tidak_menyimpan(app_riasec, clean_db):
    h = masuk(app_riasec)
    d = ok(kirim(app_riasec, h, {}))
    assert d["skor_norm"] == {} and d["holland_code"] is None and d["dimensi_teratas"] == []
    assert d["tersimpan"] is False and d["keyakinan"] == "rendah"
    assert "tidak disimpan" in d["catatan"]
    assert hitung_baris(clean_db, "riasec_hasil") == 0


# ------------------------------------------------------------------ cek kualitas (keyakinan rendah)


@pytest.mark.db
def test_cek_jawaban_seragam(app_riasec):
    d = ok(kirim(app_riasec, masuk(app_riasec), dict.fromkeys(SEHAT, 3), simpan=False))
    assert d["keyakinan"] == "rendah"
    assert any("seragam" in a for a in d["alasan_keyakinan"])
    assert d["skor_norm"]  # hasil tidak ditolak, tetap dihitung
    assert "Keyakinan rendah:" in d["catatan"]


@pytest.mark.db
def test_cek_profil_datar_tanpa_jawaban_seragam(app_riasec):
    datar = jawab({d: [3, 4, 3, 4] for d in DIM})  # nilai 3 dan 4 seimbang: tidak seragam
    d = ok(kirim(app_riasec, masuk(app_riasec), datar, simpan=False))
    alasan = " ".join(d["alasan_keyakinan"])
    assert "datar" in alasan and "seragam" not in alasan
    assert d["keyakinan"] == "rendah"


@pytest.mark.db
def test_cek_terlalu_sedikit_terjawab_per_dimensi(app_riasec):
    h = masuk(app_riasec)
    # konvensional: 2 dari 4 butir (0,5) < 0,6 -> dihitung tetapi keyakinan rendah
    jaw = {k: v for k, v in SEHAT.items() if k not in ("kon-3", "kon-4")}
    d = ok(kirim(app_riasec, h, jaw, simpan=False))
    assert "konvensional" in d["skor_norm"]
    assert any("terlalu sedikit" in a and "konvensional" in a for a in d["alasan_keyakinan"])
    assert d["keyakinan"] == "rendah"


@pytest.mark.db
def test_ambang_cek_dari_config_bukan_hardcode(clean_db, app_config, tmp_path):
    longgar = app_config.riasec.model_copy(
        update={"min_selisih_skor": 0.0, "maks_rasio_jawaban_seragam": 1.0}
    )
    cfg = app_config.model_copy(update={"riasec": longgar})
    tulis_instrumen(tmp_path / "r")
    app = create_app(make_settings(riasec_dir=str(tmp_path / "r")), cfg, clean_db)
    with TestClient(app) as c:
        seragam = dict.fromkeys(SEHAT, 3)  # rasio 1.0 >= 1.0: tetap seragam, tetapi tidak datar
        d = ok(kirim(c, masuk(c), seragam, simpan=False))
        assert not any("datar" in a for a in d["alasan_keyakinan"])
        assert any("seragam" in a for a in d["alasan_keyakinan"])


def test_domain_instrumen_contoh_selalu_keyakinan_rendah(app_config, tmp_path):
    p = tulis_instrumen(tmp_path)
    instr = muat_instrumen(p.parent, app_config)
    kontras = domain.hitung(instr, SEHAT, app_config.riasec)
    assert kontras.keyakinan == "sedang"
    contoh = domain.hitung(
        type(instr)(**{**instr.__dict__, "contoh": True}), SEHAT, app_config.riasec
    )
    assert contoh.keyakinan == "rendah" and domain.ALASAN_CONTOH in contoh.alasan


# ------------------------------------------------------------------ set jawaban atas instrumen asli


@pytest.mark.db
def test_lima_set_jawaban_atas_instrumen_asli(app_seed):
    """Skoring deterministik atas data/riasec/instrumen_v1.json untuk lima pola jawaban."""
    soal = ok(app_seed.get("/api/v1/riasec/questions"))["item"]
    ids = {d: [b["id"] for b in soal if b["dimensi"] == d] for d in DIM}

    def jawab(pola: dict[str, list[int]]) -> dict[str, int]:
        return {i: v for d, vs in pola.items() for i, v in zip(ids[d], vs, strict=False)}

    h = masuk(app_seed)

    # 1. lengkap dan bervariasi: semua dimensi dihitung, keyakinan sedang
    d = ok(
        kirim(
            app_seed,
            h,
            jawab(
                {
                    "realistis": [4, 4, 4, 4, 3, 4],
                    "investigatif": [3, 4, 3, 4, 3, 4],
                    "artistik": [2, 1, 2, 1, 2, 1],
                    "sosial": [2, 3, 2, 3, 2, 3],
                    "enterprising": [1, 0, 1, 0, 1, 0],
                    "konvensional": [3, 3, 4, 3, 3, 4],
                }
            ),
            simpan=False,
        )
    )
    assert d["skor_norm"] == {
        "realistis": 0.9583,
        "investigatif": 0.875,
        "artistik": 0.375,
        "sosial": 0.625,
        "enterprising": 0.125,
        "konvensional": 0.8333,
    }
    assert d["dimensi_teratas"] == ["realistis", "investigatif", "konvensional"]
    assert d["holland_code"] == "RIC" and d["dimensi_tidak_dihitung"] == []
    assert d["keyakinan"] == "sedang" and d["alasan_keyakinan"] == []

    # 2. parsial: dimensi di bawah min_terjawab tidak dihitung (bukan dianggap 0)
    d = ok(
        kirim(
            app_seed,
            h,
            jawab(
                {
                    "realistis": [4, 4, 3],
                    "investigatif": [3, 4, 3],
                    "sosial": [2, 2],
                    "artistik": [1],
                }
            ),
            simpan=False,
        )
    )
    assert set(d["skor_norm"]) == {"realistis", "investigatif", "sosial"}
    assert d["dimensi_tidak_dihitung"] == ["artistik", "enterprising", "konvensional"]
    assert d["terjawab"] == 9 and d["keyakinan"] == "rendah"
    assert any("terlalu sedikit" in a for a in d["alasan_keyakinan"])

    # 3. tersebar: nilai merata di seluruh skala tetapi tiap dimensi tetap berbeda
    d = ok(
        kirim(
            app_seed,
            h,
            jawab(
                {
                    "realistis": [4, 4, 4, 3, 4, 3],
                    "investigatif": [3, 3, 2, 3, 3, 2],
                    "artistik": [2, 1, 1, 2, 1, 1],
                    "sosial": [2, 2, 1, 2, 2, 1],
                    "enterprising": [0, 1, 0, 1, 0, 1],
                    "konvensional": [3, 2, 3, 2, 3, 2],
                }
            ),
            simpan=False,
        )
    )
    assert d["holland_code"] == "RIC" and d["keyakinan"] == "sedang"
    assert set(d["skor_norm"]) == set(DIM) and len(set(d["skor_norm"].values())) == 6

    # 4. seragam: semua nilai sama -> keyakinan rendah (hasil tetap dihitung)
    d = ok(kirim(app_seed, h, {b["id"]: 3 for b in soal}, simpan=False))
    assert set(d["skor_norm"].values()) == {0.75}
    assert d["keyakinan"] == "rendah" and any("seragam" in a for a in d["alasan_keyakinan"])

    # 5. datar: nilai beragam tetapi rerata tiap dimensi sama -> profil datar
    d = ok(kirim(app_seed, h, jawab({d0: [3, 4] * 3 for d0 in DIM}), simpan=False))
    assert set(d["skor_norm"].values()) == {0.875}
    assert d["keyakinan"] == "rendah"
    assert any("datar" in a for a in d["alasan_keyakinan"])
    assert not any("seragam" in a for a in d["alasan_keyakinan"])


# ------------------------------------------------------------------ validasi masukan


@pytest.mark.db
@pytest.mark.parametrize(
    "body,field",
    [
        ({"jawaban": {"tidak-ada": 3}}, "jawaban.tidak-ada"),
        ({"jawaban": {"rea-1": 6}}, "jawaban.rea-1"),
        ({"jawaban": {"rea-1": 0}}, "jawaban.rea-1"),
        ({"jawaban": {"rea-1": 3.5}}, "jawaban.rea-1"),
        ({"jawaban": {"rea-1": "3"}}, "jawaban.rea-1"),
        ({"jawaban": {"rea-1": 3}, "simpan": "ya"}, "simpan"),
        ({"jawaban": {"rea-1": 3}, "ekstra": 1}, "ekstra"),
        ({}, "jawaban"),
        ({"jawaban": {"Rea1": 3}}, "jawaban.Rea1"),  # pola id: huruf kecil dulu
        ({"jawaban": {"1rea": 3}}, "jawaban.1rea"),
        ({"jawaban": {"rea 1": 3}}, "jawaban.rea 1"),
    ],
)
def test_validasi_422(app_riasec, body, field):
    r = app_riasec.post("/api/v1/riasec/submit", json=body, headers=masuk(app_riasec))
    assert r.status_code == 422
    e = r.json()["error"]
    assert e["kode"] == "validasi_gagal"
    assert field in {f["field"] for f in e["detail"]["field"]}


# ------------------------------------------------------------------ penyimpanan & pemetaan ke profil


@pytest.mark.db
def test_pratinjau_tidak_menulis_apa_pun(app_riasec, clean_db):
    h = masuk(app_riasec)
    d = ok(kirim(app_riasec, h, SEHAT, simpan=False))
    assert d["tersimpan"] is False
    assert app_riasec.get("/api/v1/profile", headers=h).json()["profil"]["minat"] is None
    assert hitung_baris(clean_db, "riasec_hasil") == 0


@pytest.mark.db
def test_simpan_memetakan_skor_ke_profil_minat(app_riasec, clean_db):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, SEHAT))
    minat = app_riasec.get("/api/v1/profile", headers=h).json()["profil"]["minat"]
    assert minat == SKOR_SEHAT  # enam dimensi, 0..1
    assert hitung_baris(clean_db, "riasec_hasil") == 1


@pytest.mark.db
def test_kirim_ulang_mengganti_minat_dan_menghapus_dimensi_yang_tidak_dihitung(app_riasec):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, SEHAT))
    parsial = {k: v for k, v in SEHAT.items() if k.startswith(("rea", "inv"))}
    ok(kirim(app_riasec, h, parsial))
    minat = app_riasec.get("/api/v1/profile", headers=h).json()["profil"]["minat"]
    assert set(minat) == {"realistis", "investigatif"}  # dimensi lama tidak tertinggal


@pytest.mark.db
def test_jawaban_mentah_tidak_disimpan(app_riasec, clean_db):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, SEHAT))
    with clean_db.connect() as conn:
        kolom = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='riasec_hasil'"
                )
            ).scalars()
        )
        baris = conn.execute(text("SELECT skor_norm, alasan FROM riasec_hasil")).one()
    assert not any("jawab" in k for k in kolom - {"terjawab"})
    assert "rea-1" not in json.dumps(baris[0]) and "rea-1" not in json.dumps(baris[1])


@pytest.mark.db
def test_hasil_ikut_terhapus_bersama_sesi(app_riasec, clean_db):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, SEHAT))
    assert hitung_baris(clean_db, "riasec_hasil") == 1
    assert app_riasec.delete("/api/v1/session", headers=h).status_code == 204
    assert hitung_baris(clean_db, "riasec_hasil") == 0  # CASCADE: tidak melebihi umur sesi


@pytest.mark.db
def test_submit_dibatasi_rate_limit_per_sesi(clean_db, app_config, tmp_path):
    from app.core.config import Batas

    rl = app_config.rate_limit.model_copy(update={"per_sesi": Batas(maks=2, jendela_detik=60)})
    tulis_instrumen(tmp_path / "r")
    app = create_app(
        make_settings(riasec_dir=str(tmp_path / "r")),
        app_config.model_copy(update={"rate_limit": rl}),
        clean_db,
    )
    with TestClient(app) as c:
        h = masuk(c)
        kode = [kirim(c, h, {}, simpan=False).status_code for _ in range(3)]
        assert kode == [200, 200, 429]


@pytest.mark.db
def test_jawaban_riasec_tidak_ke_llm_dan_tidak_tercatat_di_log(
    clean_db, app_config, tmp_path, caplog
):
    from tests.fakes import FakeLLM

    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    tulis_instrumen(tmp_path / "r")
    fake = FakeLLM()
    app = create_app(
        make_settings(riasec_dir=str(tmp_path / "r")), app_config, clean_db, llm_client=fake
    )
    with caplog.at_level("DEBUG"), TestClient(app) as c:
        h = masuk(c)
        ok(kirim(c, h, SEHAT))
        ok(c.post("/api/v1/explore", json={}, headers=h))
    assert fake.panggilan_generate == 0 and fake.panggilan_embed == 0  # tes minat tanpa LLM
    log = " ".join(r.getMessage() for r in caplog.records)
    assert not any(butir in log for butir in SEHAT), "id butir/jawaban RIASEC muncul di log"


# ------------------------------------------------------------------ integrasi /explore


def jelajah(c, h, **body):
    return ok(c.post("/api/v1/explore", json=body, headers=h))


@pytest.mark.db
def test_explore_menandai_minat_berkeyakinan_rendah(app_riasec):
    h = masuk(app_riasec)
    assert jelajah(app_riasec, h)["minat_sumber"]["sumber"] == "belum_diisi"
    ok(kirim(app_riasec, h, dict.fromkeys(SEHAT, 3)))  # seragam: keyakinan rendah
    d = jelajah(app_riasec, h, top_n=3)
    assert d["minat_sumber"]["sumber"] == "riasec" and d["minat_sumber"]["keyakinan"] == "rendah"
    assert d["minat_sumber"]["alasan"] and d["minat_sumber"]["versi_instrumen"] == "uji-v1"
    assert all(r["keyakinan_minat"] == "rendah" for r in d["rekomendasi"])
    assert any("keyakinan rendah" in c for c in d["catatan"])


@pytest.mark.db
def test_explore_minat_keyakinan_sedang_tanpa_peringatan(app_riasec):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, SEHAT))
    d = jelajah(app_riasec, h, top_n=3)
    assert d["minat_sumber"]["keyakinan"] == "sedang"
    assert all(r["keyakinan_minat"] == "sedang" for r in d["rekomendasi"])
    assert not any("keyakinan rendah" in c for c in d["catatan"])


@pytest.mark.db
def test_explore_minat_diubah_manual_tidak_lagi_dianggap_hasil_tes(app_riasec):
    h = masuk(app_riasec)
    ok(kirim(app_riasec, h, dict.fromkeys(SEHAT, 3)))
    app_riasec.put("/api/v1/profile", json={"minat": {"sosial": 0.9}}, headers=h)
    d = jelajah(app_riasec, h, top_n=3)
    assert d["minat_sumber"] == {"sumber": "manual", "keyakinan": None, "alasan": []}
    assert all(r["keyakinan_minat"] is None for r in d["rekomendasi"])


@pytest.mark.db
def test_explore_urutan_dan_skor_sama_dengan_minat_manual_yang_identik(app_riasec):
    """Penanda keyakinan tidak boleh mengubah logika rekomendasi."""
    a, b = masuk(app_riasec), masuk(app_riasec)
    ok(kirim(app_riasec, a, SEHAT))
    app_riasec.put("/api/v1/profile", json={"minat": SKOR_SEHAT}, headers=b)

    def inti(d):
        return [(r["rumpun"], r["skor_kecocokan"], r["komponen"]) for r in d["rekomendasi"]]

    assert inti(jelajah(app_riasec, a, top_n=10)) == inti(jelajah(app_riasec, b, top_n=10))


@pytest.mark.db
def test_explore_dengan_instrumen_contoh_selalu_ditandai_rendah(app_contoh):
    h = masuk(app_contoh)
    contoh = ok(app_contoh.get("/api/v1/riasec/questions"))
    jaw = {b["id"]: (5 if b["dimensi"] in DIM[:2] else 1) for b in contoh["item"]}
    d = ok(kirim(app_contoh, h, jaw))
    assert d["keyakinan"] == "rendah" and domain.ALASAN_CONTOH in d["alasan_keyakinan"]
    e = jelajah(app_contoh, h)
    assert e["minat_sumber"]["keyakinan"] == "rendah"
    assert e["minat_sumber"]["instrumen_contoh"] is True


@pytest.mark.db
def test_explore_persona_tanpa_tes_tetap_manual(app_seed):
    h = muat_persona(app_seed, "rani")
    assert jelajah(app_seed, h)["minat_sumber"]["sumber"] == "manual"


# ------------------------------------------------------------------ pemuatan instrumen & config


def test_instrumen_dan_config_tidak_valid_gagal_cepat(app_config, tmp_path):
    base = json.loads(tulis_instrumen(tmp_path / "ok").read_text())
    p = tmp_path / "x.json"

    def coba(**ubah):
        return parse_instrumen({**base, **ubah}, DIM, p)

    coba()  # valid
    butir = base["item"]
    with pytest.raises(ConfigError, match="id butir ganda"):
        coba(item=[*butir, butir[0]])
    with pytest.raises(ConfigError, match="tidak dikenal"):
        coba(item=[*butir, {"id": "z", "teks": "t", "dimensi": "astronomi"}])
    with pytest.raises(ConfigError, match="dimensi tanpa butir"):
        coba(item=[b for b in butir if b["dimensi"] != "sosial"])
    with pytest.raises(ConfigError, match="dimensi harus tepat sama"):
        coba(dimensi=DIM[:5])
    with pytest.raises(ConfigError, match="lebih kecil"):
        coba(skala={"min": 5, "maks": 5})
    with pytest.raises(ConfigError, match="bilangan bulat"):
        coba(skala={"min": 1.5, "maks": 5})
    with pytest.raises(ConfigError, match="kunci wajib"):
        parse_instrumen({"versi_instrumen": "x"}, DIM, p)
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        muat_instrumen(tmp_path / "kosong", app_config)


def test_instrumen_json_rusak_dan_bom_diterima(app_config, tmp_path):
    f = tmp_path / "bom"
    tulis_instrumen(f)
    p = f / "instrumen_v1.json"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())  # Windows sering menambah BOM
    assert muat_instrumen(f, app_config).versi_instrumen == "uji-v1"
    p.write_text("{rusak", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        muat_instrumen(f, app_config)


def test_config_riasec_tidak_konsisten_gagal_start(tmp_path, app_config):
    teks = Path(app_config_path()).read_text(encoding="utf-8")
    rusak = tmp_path / "app.yaml"
    rusak.write_text(teks.replace("realistis: R,", "realistis: X, "), encoding="utf-8")
    assert load_app_config(rusak)  # huruf unik tetap valid
    ganda = tmp_path / "ganda.yaml"
    ganda.write_text(teks.replace("investigatif: I,", "investigatif: R,"), encoding="utf-8")
    with pytest.raises(ConfigError, match="huruf unik"):
        load_app_config(ganda)
    hilang = tmp_path / "hilang.yaml"
    hilang.write_text(teks.replace("konvensional: C}", "}"), encoding="utf-8")
    with pytest.raises(ConfigError, match="kode_huruf"):
        load_app_config(hilang)


def app_config_path() -> str:
    from app.core.config import Settings

    return Settings(_env_file=None).app_config_path
