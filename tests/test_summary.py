"""Task 11: POST /summary (ringkasan deterministik, FR-R1, FR-R2)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.ringkasan import fokus_satu_pilihan, gabung_fokus, rata_mapel
from app.ingest.service import ingest
from tests.helpers import analyze, masuk, muat_persona, put_profil

pytestmark = pytest.mark.db

IK, AKUN, HUKUM = "ui-ilmu-komputer", "ui-akuntansi", "ui-hukum"


def simpan(c, h, jalur, pilihan, **lain):
    body = {"jalur": jalur, "pilihan": [{"prodi_id": p} for p in pilihan], "simpan": True, **lain}
    r = c.post("/api/v1/strategy", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["disimpan"] is True
    return r.json()["strategy_id"]


def ringkas(c, h, **body):
    return c.post("/api/v1/summary", json=body, headers=h)


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def tanpa_waktu(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "dihasilkan_pada"}


# ---------------------------- akses & privasi (FR-R2) ----------------------------


def test_wajib_token(app_seed):
    assert app_seed.post("/api/v1/summary", json={}).status_code == 401
    assert app_seed.post("/api/v1/summary").status_code == 401


def test_tidak_ada_endpoint_publik_atau_tautan_bagi(app_seed):
    """Tidak ada GET/URL yang mengembalikan ringkasan; hanya POST /summary yang butuh token."""
    paths = app_seed.app.openapi()[
        "paths"
    ]  # app.routes bersarang di FastAPI ini; OpenAPI = daftar rute rata
    rute = {
        p: sorted(m) for p, m in paths.items() if "summary" in p.lower() or "ringkasan" in p.lower()
    }
    assert rute == {"/api/v1/summary": ["post"]}
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK, AKUN])
    for path in (
        "/api/v1/summary",
        "/api/v1/summary/share",
        "/api/v1/summary/abc",
        "/api/v1/ringkasan",
    ):
        assert app_seed.get(path, headers=h).status_code in (404, 405)
    d = ok(ringkas(app_seed, h))
    assert "http" not in " ".join(k for k in d)  # tidak ada kunci tautan
    assert not any(k in d for k in ("url_bagikan", "share_url", "token_bagi"))


def test_strategi_sesi_lain_tidak_bisa_diakses(app_seed):
    a = muat_persona(app_seed, "rani")
    sid = simpan(app_seed, a, "SNBT", [IK])
    b = muat_persona(app_seed, "dimas")
    r = ringkas(app_seed, b, strategy_id=sid)
    assert r.status_code == 404 and r.json()["error"]["kode"] == "strategi_tidak_ditemukan"
    assert ringkas(app_seed, b).json()["error"]["kode"] == "strategi_belum_disimpan"


# ---------------------------- isi ringkasan ----------------------------


def test_belum_ada_strategi_tersimpan_404(app_seed):
    h = muat_persona(app_seed, "rani")
    r = ringkas(app_seed, h)
    assert r.status_code == 404 and r.json()["error"]["kode"] == "strategi_belum_disimpan"
    assert "simpan=true" in r.json()["error"]["pesan"]


def test_ringkasan_lengkap_untuk_satu_jalur(app_seed):
    h = muat_persona(app_seed, "rani")
    sid = simpan(app_seed, h, "SNBT", [IK, AKUN])
    d = ok(ringkas(app_seed, h))

    assert set(d) >= {
        "dihasilkan_pada",
        "pilihan_akhir",
        "alasan",
        "gap",
        "fokus_persiapan",
        "dokumen_syarat",
        "catatan",
        "narasi",
        "narasi_fallback",
        "strategi",
    }
    assert d["narasi_fallback"] is True and "ui-ilmu-komputer" not in d["narasi"]
    assert [p["prodi_id"] for p in d["pilihan_akhir"]] == [IK, AKUN]
    assert [p["urutan"] for p in d["pilihan_akhir"]] == [1, 2]
    p = d["pilihan_akhir"][0]
    assert (p["jalur"], p["prodi"], p["ptn"], p["status_gate"]) == (
        "SNBT",
        "Ilmu Komputer",
        "Universitas Indonesia",
        "lolos",
    )
    assert p["kategori"] in ("reach", "match", "safe") and p["indikatif"] is True and p["alasan"]
    assert p["status_verifikasi"] == "belum_diverifikasi"
    assert d["strategi"][0]["strategy_id"] == sid and d["strategi"][0]["komposisi"]["jumlah"] == 2
    assert "SNBT: 2 pilihan" in d["alasan"][0]


def test_angka_dan_status_sama_dengan_mesin_aturan(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK, AKUN])
    d = ok(ringkas(app_seed, h))
    a = ok(analyze(app_seed, h, [{"prodi_id": p, "jalur": ["SNBT"]} for p in (IK, AKUN)]))["hasil"]
    for pil, hasil in zip(d["pilihan_akhir"], a, strict=True):
        assert pil["kategori"] == hasil["penilaian"]["kategori"]
        assert pil["keyakinan"] == hasil["penilaian"]["keyakinan"]
        assert pil["alasan"] == hasil["penilaian"]["alasan"]
        assert pil["status_gate"] == hasil["gate"]["status"]


def test_dokumen_syarat_dari_data_terkurasi_dengan_sumber(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])
    docs = ok(ringkas(app_seed, h))["dokumen_syarat"]
    assert len(docs) == 8 and {x["jalur"] for x in docs} == {"SNBT"}
    nama = [x["nama"] for x in docs]
    assert any("Akun SNPMB" in n for n in nama) and any("Portofolio" in n for n in nama)
    assert all(x["sumber_url"].startswith("https://") for x in docs)
    assert all(x["status_verifikasi"] == "belum_diverifikasi" for x in docs)
    assert any("sumber sekunder" in n for n in nama)  # penanda dari tim data tetap terbawa


def test_dua_jalur_memakai_strategi_terbaru_per_jalur(app_seed):
    h = muat_persona(app_seed, "dimas")
    simpan(app_seed, h, "SNBT", [IK])  # strategi lama
    simpan(app_seed, h, "SNBP", ["ui-teknik-industri", "ui-teknik-elektro"])
    baru = simpan(app_seed, h, "SNBT", [AKUN, HUKUM])
    d = ok(ringkas(app_seed, h))
    ringkas_jalur = [(p["jalur"], p["prodi_id"]) for p in d["pilihan_akhir"]]
    assert ringkas_jalur == [
        ("SNBP", "ui-teknik-industri"),
        ("SNBP", "ui-teknik-elektro"),
        ("SNBT", AKUN),
        ("SNBT", HUKUM),
    ]
    assert [s["jalur"] for s in d["strategi"]] == ["SNBP", "SNBT"] and d["strategi"][1][
        "strategy_id"
    ] == baru
    assert {x["jalur"] for x in d["dokumen_syarat"]} == {"SNBP", "SNBT"}
    assert len([x for x in d["dokumen_syarat"] if x["jalur"] == "SNBP"]) == 5
    assert any("Lulus SNBP menutup" in c for c in d["catatan"])


def test_strategy_id_memilih_strategi_tertentu(app_seed):
    h = muat_persona(app_seed, "rani")
    lama = simpan(app_seed, h, "SNBT", [IK])
    simpan(app_seed, h, "SNBT", [AKUN])
    d = ok(ringkas(app_seed, h, strategy_id=lama))
    assert [p["prodi_id"] for p in d["pilihan_akhir"]] == [IK]
    assert ok(ringkas(app_seed, h))["pilihan_akhir"][0]["prodi_id"] == AKUN


def test_permintaan_tidak_valid_422(app_seed):
    h = muat_persona(app_seed, "rani")
    assert ringkas(app_seed, h, strategy_id="bukan-uuid").status_code == 422
    assert ringkas(app_seed, h, lain="x").status_code == 422


def test_deterministik_selain_waktu(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK, AKUN, "ui-v-akuntansi-d3"])
    pertama, kedua = ok(ringkas(app_seed, h)), ok(ringkas(app_seed, h))
    assert tanpa_waktu(pertama) == tanpa_waktu(kedua)


def test_ringkasan_tidak_menulis_apa_pun(app_seed, clean_db):
    from sqlalchemy import text

    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])

    def snap():
        with clean_db.connect() as conn:
            return [tuple(r) for r in conn.execute(text("SELECT * FROM strategies"))], [
                tuple(r) for r in conn.execute(text("SELECT * FROM profiles"))
            ]

    sebelum = snap()
    ringkas(app_seed, h)
    assert snap() == sebelum


# ---------------------------- fokus persiapan: diturunkan dari gap ----------------------------


def test_gap_dan_fokus_skor_dari_acuan(app_seed, clean_db):
    with Session(clean_db) as db:
        assert ingest(
            db,
            "acuan",
            [
                {
                    "prodi_id": IK,
                    "jalur": "SNBT",
                    "rendah": "660",
                    "tinggi": "720",
                    "tahun": "2025",
                    "sumber_url": "https://contoh.id/a",
                }
            ],
        ).ok
    h = muat_persona(app_seed, "rani")
    put_profil(app_seed, h, skor_tryout=620)
    simpan(app_seed, h, "SNBT", [IK])
    d = ok(ringkas(app_seed, h))
    assert d["gap"] == [{"jalur": "SNBT", "prodi_id": IK, "gap": 40, "satuan": "poin skor tryout"}]
    fokus = [f for f in d["fokus_persiapan"] if f["jenis"] == "skor_tryout"]
    assert fokus and "40 poin" in fokus[0]["pesan"] and "660" in fokus[0]["pesan"]
    assert d["pilihan_akhir"][0]["gap"] == 40 and d["pilihan_akhir"][0]["kategori"] == "reach"
    assert any("siklus sebelumnya" in c for c in d["catatan"])  # label acuan siklus sebelumnya


def test_fokus_dari_faktor_terlemah_untuk_reach_dan_match(app_seed):
    h = muat_persona(app_seed, "rani")
    lemah_rapor = {
        "nilai_rapor": {
            f"semester_{i}": dict.fromkeys(
                ("matematika", "fisika", "kimia", "biologi", "bahasa_indonesia", "bahasa_inggris"),
                62,
            )
            for i in range(1, 6)
        }
    }
    put_profil(app_seed, h, **lemah_rapor)
    simpan(
        app_seed, h, "SNBT", ["ui-v-akuntansi-d3", "ui-v-hubungan-masyarakat"]
    )  # keduanya pita tinggi
    d = ok(ringkas(app_seed, h))
    jenis = {f["jenis"] for f in d["fokus_persiapan"]}
    assert jenis & {"faktor_rapor", "faktor_tren", "faktor_peringkat"}
    gabungan = [f for f in d["fokus_persiapan"] if f["jenis"].startswith("faktor_")]
    assert gabungan and set(gabungan[0]["prodi_ids"]) == {
        "ui-v-akuntansi-d3",
        "ui-v-hubungan-masyarakat",
    }  # digabung


def test_pilihan_safe_diberi_fokus_pertahankan(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])
    d = ok(ringkas(app_seed, h))
    assert d["pilihan_akhir"][0]["kategori"] == "safe"
    assert [f["jenis"] for f in d["fokus_persiapan"]] == ["pertahankan"]


def test_fokus_mapel_penentu_bila_ada_datanya(app_seed, clean_db):
    with Session(clean_db) as db:
        assert ingest(
            db,
            "katalog",
            [
                {
                    "prodi_id": IK,
                    "ptn_id": "ui",
                    "nama": "Ilmu Komputer",
                    "rumpun": "Teknologi Informasi",
                    "jenjang": "Sarjana",
                    "program": "akademik",
                    "jalur_dibuka": "SNBT",
                    "mapel_penentu": "matematika|fisika",
                    "daya_tampung": "75",
                    "peminat_tahun_lalu": "2132",
                    "sumber_url": "https://contoh.id/x",
                }
            ],
        ).ok
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])
    fokus = [
        f for f in ok(ringkas(app_seed, h))["fokus_persiapan"] if f["jenis"] == "mapel_penentu"
    ]
    assert (
        len(fokus) == 1 and "fisika" in fokus[0]["pesan"] and "84" in fokus[0]["pesan"]
    )  # fisika 84,2 < matematika 87,8


def test_pilihan_tidak_memenuhi_syarat_tetap_masuk_dengan_alasan(app_seed):
    h = muat_persona(app_seed, "budi")  # lulus 2023
    simpan(app_seed, h, "SNBT", [IK])
    d = ok(ringkas(app_seed, h))
    p = d["pilihan_akhir"][0]
    assert p["status_gate"] == "tidak_memenuhi_syarat" and p["kategori"] is None
    assert "lulusan lebih lama" in p["alasan"]
    fokus = d["fokus_persiapan"][0]
    assert fokus["jenis"] == "syarat" and "tidak memenuhi syarat SNBT" in fokus["pesan"]
    assert len(d["dokumen_syarat"]) == 8  # dokumen tetap ditampilkan


def test_pilihan_data_kurang_diminta_melengkapi(app_seed):
    h = muat_persona(app_seed, "sinta")
    simpan(app_seed, h, "SNBT", [IK])
    d = ok(ringkas(app_seed, h))
    assert (
        d["pilihan_akhir"][0]["status_gate"] == "data_kurang"
        and d["pilihan_akhir"][0]["kategori"] is None
    )
    assert (
        d["fokus_persiapan"][0]["jenis"] == "data"
        and "wni_punya_nik" in d["fokus_persiapan"][0]["pesan"]
    )


def test_ringkasan_mengikuti_profil_terkini_bukan_snapshot(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])
    assert ok(ringkas(app_seed, h))["pilihan_akhir"][0]["status_gate"] == "lolos"
    put_profil(app_seed, h, tahun_lulus=2023)
    assert ok(ringkas(app_seed, h))["pilihan_akhir"][0]["status_gate"] == "tidak_memenuhi_syarat"


def test_pelanggaran_aturan_muncul_di_narasi_dan_alasan(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK, AKUN, HUKUM])  # 3 Sarjana: butuh vokasi
    d = ok(ringkas(app_seed, h))
    assert "1 pelanggaran aturan" in d["alasan"][0]
    assert "perlu diperbaiki" in d["narasi"]
    assert any(t["kode"] == "butuh_vokasi" for t in d["strategi"][0]["temuan"])


def test_catatan_menandai_data_belum_diverifikasi_dan_sifat_indikatif(app_seed):
    h = muat_persona(app_seed, "rani")
    simpan(app_seed, h, "SNBT", [IK])
    catatan = " ".join(ok(ringkas(app_seed, h))["catatan"])
    assert "indikatif" in catatan and "belum diverifikasi" in catatan
    assert "proksi dari rapor" in catatan  # SNBT: keyakinan rendah dijelaskan


def test_sesi_baru_tanpa_strategi_404_walau_profil_ada(app_seed):
    h = masuk(app_seed)
    assert ringkas(app_seed, h).status_code == 404


# ---------------------------- unit murni ----------------------------


def test_rata_mapel_dan_gabung_fokus():
    profil = {
        "nilai_rapor": {
            "semester_1": {"fisika": 80, "kimia": 70},
            "semester_2": {"fisika": 90},
            "semester_6": {"fisika": 0},
        }
    }
    assert rata_mapel(profil, ["fisika", "kimia", "biologi"]) == {"fisika": 85.0, "kimia": 70.0}
    f1 = {"jalur": "SNBT", "jenis": "x", "pesan": "p", "prodi_ids": ["a"]}
    f2 = {"jalur": "SNBT", "jenis": "x", "pesan": "p", "prodi_ids": ["b", "a"]}
    f3 = {"jalur": "SNBP", "jenis": "x", "pesan": "p", "prodi_ids": ["a"]}
    assert gabung_fokus([f1, f2, f3]) == [{**f1, "prodi_ids": ["a", "b"]}, f3]


def test_fokus_tanpa_penilaian_dan_data():
    hasil = {
        "prodi_id": "p",
        "prodi": {"nama": "P"},
        "gate": {"status": "lolos", "syarat": []},
        "penilaian": {"kategori": "belum_ada_acuan", "gap": None, "tier": None},
        "data_kurang": [],
    }
    assert (
        fokus_satu_pilihan("SNBT", hasil, {}, None) == []
    )  # tidak ada dasar untuk menyarankan apa pun
