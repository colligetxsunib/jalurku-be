"""Task 18: POST /explore (FR-E1 sampai E3): rekomendasi rumpun deterministik, tanpa LLM."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import AppConfig, ConfigError, load_app_config
from app.db import models as m
from app.ingest.service import ingest, ingest_direktori
from app.main import create_app
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.helpers import SEED_DIR, masuk, muat_persona, put_profil

pytestmark = pytest.mark.db

RUMPUN_CONFIG = {
    "Teknik",
    "Teknologi Informasi",
    "Kesehatan",
    "Hukum",
    "Ekonomi dan Bisnis",
    "Psikologi",
    "Sosial dan Komunikasi",
    "Sosial dan Politik",
    "Seni dan Desain",
    "Arsitektur dan Desain",
}


def jelajah(c, h, **body):
    return c.post("/api/v1/explore", json=body, headers=h)


def ok(r) -> dict:
    assert r.status_code == 200, r.text
    return r.json()


def semua_teks(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from semua_teks(v)
    elif isinstance(x, list):
        for v in x:
            yield from semua_teks(v)


# ------------------------------------------------------------------ akses & bentuk


def test_wajib_token_dan_hanya_post(app_seed):
    assert app_seed.post("/api/v1/explore", json={}).status_code == 401
    paths = app_seed.app.openapi()["paths"]
    assert sorted(paths["/api/v1/explore"]) == ["post"]


def test_rani_rekomendasi_lengkap_sesuai_kriteria_penerimaan(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(jelajah(app_seed, h, top_n=5))
    rek = d["rekomendasi"]
    assert len(rek) == 5 and d["data_kurang"] == [] and d["indikatif"] is True
    skor = [r["skor_kecocokan"] for r in rek]
    assert skor == sorted(skor, reverse=True)
    assert {r["rumpun"] for r in rek} <= RUMPUN_CONFIG
    assert rek[0]["rumpun"] in (
        "Teknologi Informasi",
        "Teknik",
    )  # Rani: investigatif, matematika kuat
    for r in rek:
        assert set(r["komponen"]) == {"minat", "nilai"}  # komponen skor (PRD kriteria penerimaan)
        assert 0 <= r["skor_kecocokan"] <= 1 and r["alasan"].startswith("Cocok karena")
        assert len(r["contoh_profesi"]) >= 1  # minimal satu contoh profesi
        assert r["prodi_ids"] and r["total_prodi"] >= len(r["prodi_ids"])
        assert r["kelayakan"] is None  # tanpa jalur
    assert any("klasifikasi awal" in c for c in d["catatan"])


def test_skor_teknologi_informasi_cocok_dengan_hitungan_manual(app_seed):
    """Cosine minat Rani dengan profil TI = 1.315 / (1.3058 x 1.1446) = 0.88; nilai terbobot = 0.87."""
    h = muat_persona(app_seed, "rani")
    ti = next(
        r
        for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]
        if r["rumpun"] == "Teknologi Informasi"
    )
    assert ti["komponen"] == {"minat": 0.88, "nilai": 0.87}
    assert ti["skor_kecocokan"] == 0.88  # (0.8798 + 0.8746) / 2
    assert ti["bobot_efektif"] == {"minat": 0.5, "nilai": 0.5}
    assert ti["mapel_belum_diisi"] == ["informatika"]  # ditandai, tidak dihitung sebagai nol
    assert "Nilai belum diisi untuk mapel relevan: informatika." in ti["alasan"]


def test_fr_e3_ptn_yang_membuka_rumpun(app_seed):
    h = muat_persona(app_seed, "rani")
    ti = next(
        r
        for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]
        if r["rumpun"] == "Teknologi Informasi"
    )
    assert {p["id"] for p in ti["ptn"]} >= {"ui", "ugm"}
    gabungan = [i for p in ti["ptn"] for i in p["prodi_ids"]]
    assert sorted(gabungan) == sorted(ti["prodi_ids"])
    assert all(p["nama"] and p["provinsi"] for p in ti["ptn"])


def test_deterministik(app_seed):
    h = muat_persona(app_seed, "dimas")
    a, b = ok(jelajah(app_seed, h)), ok(jelajah(app_seed, h))
    assert a == b


def test_top_n_bawaan_dan_batas(app_seed, app_config):
    h = muat_persona(app_seed, "rani")
    assert len(ok(jelajah(app_seed, h))["rekomendasi"]) == app_config.explore.top_n_default
    assert len(ok(jelajah(app_seed, h, top_n=2))["rekomendasi"]) == 2
    assert len(ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]) == 10
    assert app_seed.post("/api/v1/explore", headers=h).status_code == 200  # tanpa badan
    r = jelajah(app_seed, h, top_n=11)
    assert r.status_code == 422 and r.json()["error"]["detail"]["field"][0]["field"] == "top_n"
    for salah in (
        {"top_n": 0},
        {"top_n": 99},
        {"top_n": "lima"},
        {"jalur": "MANDIRI"},
        {"lain": 1},
    ):
        assert jelajah(app_seed, h, **salah).status_code == 422, salah


def test_urutan_menurut_skor_tampil_lalu_nama_rumpun(app_seed):
    """Skor yang tampil sama -> urut alfabet, jadi urutan selalu bisa dijelaskan dari angka di layar."""
    h = muat_persona(app_seed, "dimas")
    rek = ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]
    kunci = [(-r["skor_kecocokan"], r["rumpun"]) for r in rek]
    assert kunci == sorted(kunci)
    assert len({r["skor_kecocokan"] for r in rek}) < len(rek)  # ada skor kembar pada data ini


# ------------------------------------------------------------------ data kurang (tidak menebak)


def test_profil_kosong_tanpa_rekomendasi_dan_pertanyaan(app_seed):
    h = muat_persona(app_seed, "sinta")  # tanpa minat dan rapor
    d = ok(jelajah(app_seed, h))
    assert d["rekomendasi"] == []
    assert [x["field"] for x in d["data_kurang"]] == ["minat", "nilai_rapor"]
    assert all(x["pertanyaan"] for x in d["data_kurang"])


def test_hanya_minat_skor_dari_minat_saja(app_seed):
    h = masuk(app_seed)
    put_profil(app_seed, h, minat={"artistik": 0.9, "sosial": 0.2})
    d = ok(jelajah(app_seed, h, top_n=3))
    assert [x["field"] for x in d["data_kurang"]] == ["nilai_rapor"]
    assert d["rekomendasi"][0]["rumpun"] == "Seni dan Desain"
    for r in d["rekomendasi"]:
        assert r["komponen"]["nilai"] is None and r["bobot_efektif"] == {"minat": 1.0}
        assert r["skor_kecocokan"] == r["komponen"]["minat"]


def test_hanya_nilai_skor_dari_nilai_saja(app_seed):
    h = masuk(app_seed)
    put_profil(
        app_seed,
        h,
        nilai_rapor={
            f"semester_{i}": {"biologi": 95, "kimia": 92, "matematika": 70} for i in range(1, 6)
        },
    )
    d = ok(jelajah(app_seed, h, top_n=3))
    assert [x["field"] for x in d["data_kurang"]] == ["minat"]
    assert d["rekomendasi"][0]["rumpun"] == "Kesehatan"
    for r in d["rekomendasi"]:
        assert r["komponen"]["minat"] is None and r["bobot_efektif"] == {"nilai": 1.0}
        assert "Minat belum diisi" in r["alasan"]


def test_minat_semua_nol_dianggap_belum_diisi(app_seed):
    h = masuk(app_seed)
    put_profil(app_seed, h, minat={"realistis": 0.0, "sosial": 0.0})
    d = ok(jelajah(app_seed, h))
    assert d["rekomendasi"] == [] and "minat" in [x["field"] for x in d["data_kurang"]]


def test_nilai_pada_mapel_tak_relevan_tidak_menghasilkan_skor_nilai(app_seed):
    h = masuk(app_seed)
    put_profil(app_seed, h, nilai_rapor={"semester_1": {"mapel_lain": 90}})
    d = ok(jelajah(app_seed, h))
    assert d["rekomendasi"] == [] and "nilai_rapor" in [x["field"] for x in d["data_kurang"]]


# ------------------------------------------------------------------ kelayakan (gate + penilaian)


def test_kelayakan_snbt_memakai_mesin_yang_sama(app_seed):
    h = muat_persona(app_seed, "dimas")
    d = ok(jelajah(app_seed, h, top_n=3, jalur="SNBT"))
    assert d["jalur"] == "SNBT"
    teknik = next(r for r in d["rekomendasi"] if r["rumpun"] == "Teknik")
    k = teknik["kelayakan"]
    assert k["jalur"] == "SNBT" and k["gate"] == "lolos" and k["indikatif"] is True
    assert k["jumlah_prodi_dinilai"] == 30 and k["dari_total_prodi"] == 60
    assert sum(k["kategori"].values()) == 30
    assert set(k["kategori"]) <= {"reach", "match", "safe", "belum_ada_acuan", "tanpa_penilaian"}
    assert k["kategori"].get("match", 0) >= 1  # prodi UI yang punya data keketatan didahulukan
    assert any("Sertakan jalur" in c for c in ok(jelajah(app_seed, h))["catatan"])


def test_kelayakan_konsisten_dengan_analyze(app_seed):
    h = muat_persona(app_seed, "rani")
    d = ok(jelajah(app_seed, h, top_n=10, jalur="SNBT"))
    seni = next(r for r in d["rekomendasi"] if r["rumpun"] == "Seni dan Desain")
    ids = seni["prodi_ids"]
    hasil = app_seed.post(
        "/api/v1/analyze",
        json={"targets": [{"prodi_id": i, "jalur": ["SNBT"]} for i in ids]},
        headers=h,
    ).json()["hasil"]
    from collections import Counter

    harap = Counter(
        x["penilaian"]["kategori"] if x["penilaian"] else "tanpa_penilaian" for x in hasil
    )
    assert seni["kelayakan"]["kategori"] == dict(sorted(harap.items()))


def test_kelayakan_snbp_meminta_konfirmasi_syarat_prodi(app_seed):
    h = muat_persona(app_seed, "rani")  # belum mengonfirmasi syarat khusus prodi apa pun
    k = ok(jelajah(app_seed, h, top_n=1, jalur="SNBP"))["rekomendasi"][0]["kelayakan"]
    assert k["gate"] == "data_kurang"
    assert any(f.startswith("konfirmasi_syarat_prodi.") for f in k["data_kurang"])


def test_kelayakan_gagal_syarat_dilaporkan_apa_adanya(app_seed):
    h = muat_persona(app_seed, "budi")
    put_profil(
        app_seed,
        h,
        minat={"realistis": 0.8, "investigatif": 0.7},
        nilai_rapor={f"semester_{i}": {"matematika": 80, "fisika": 80} for i in range(1, 6)},
    )
    k = ok(jelajah(app_seed, h, top_n=1, jalur="SNBT"))["rekomendasi"][0]["kelayakan"]
    assert k["gate"] == "tidak_memenuhi_syarat" and k["kategori"] == {
        "tanpa_penilaian": k["jumlah_prodi_dinilai"]
    }


def test_batas_prodi_dinilai_dari_config(clean_db: Engine, app_config: AppConfig):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    kecil = app_config.explore.model_copy(update={"maks_prodi_kelayakan": 3})
    app = create_app(make_settings(), app_config.model_copy(update={"explore": kecil}), clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        h = muat_persona(c, "rani")
        k = ok(jelajah(c, h, top_n=1, jalur="SNBT"))["rekomendasi"][0]["kelayakan"]
    assert k["jumlah_prodi_dinilai"] == 3 and k["dari_total_prodi"] > 3


# ------------------------------------------------------------------ data menggantikan klasifikasi awal


def test_tag_minat_dan_mapel_penentu_di_prodi_dipakai_menggantikan_klasifikasi_awal(
    app_seed, clean_db: Engine
):
    h = muat_persona(app_seed, "rani")
    awal = {r["rumpun"]: r for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]}[
        "Seni dan Desain"
    ]
    with Session(clean_db) as db:
        for p in db.query(m.Prodi).filter(m.Prodi.rumpun == "Seni dan Desain"):
            p.tag_minat = ["investigatif", "realistis"]
            p.mapel_penentu = ["matematika", "fisika"]
        db.commit()
    rek = {r["rumpun"]: r for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]}
    seni = rek["Seni dan Desain"]
    assert seni["sumber_profil"]["minat"] == "data" and seni["sumber_profil"]["mapel"] == "data"
    assert awal["sumber_profil"]["minat"] == "klasifikasi_awal"
    # Rani: (0.85 + 0.6) / (1.3058 x sqrt(2)) = 0.785 -> kini berprofil investigatif + realistis
    assert seni["komponen"]["minat"] == 0.79 > awal["komponen"]["minat"]
    assert seni["mapel_belum_diisi"] == []
    assert rek["Teknik"]["sumber_profil"]["minat"] == "klasifikasi_awal"  # rumpun lain tetap


def test_tag_minat_tak_dikenal_diabaikan(app_seed, clean_db: Engine):
    with Session(clean_db) as db:
        for p in db.query(m.Prodi).filter(m.Prodi.rumpun == "Hukum"):
            p.tag_minat = ["tidak_ada_dimensi"]
        db.commit()
    h = muat_persona(app_seed, "rani")
    hukum = next(
        r for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"] if r["rumpun"] == "Hukum"
    )
    assert hukum["sumber_profil"]["minat"] == "klasifikasi_awal"


def test_rumpun_tanpa_profil_sama_sekali_tidak_ditebak(app_seed, clean_db: Engine):
    with Session(clean_db) as db:
        db.add(
            m.Prodi(
                id="ui-agro",
                ptn_id="ui",
                nama="Agroteknologi",
                rumpun="Pertanian",
                jenjang="S1",
                program="akademik",
            )
        )
        db.commit()
    h = muat_persona(app_seed, "rani")
    assert "Pertanian" not in {
        r["rumpun"] for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]
    }


def test_rumpun_di_config_tanpa_prodi_di_katalog_tidak_muncul(
    clean_db: Engine, app_config: AppConfig
):
    """Hanya rumpun yang benar-benar ada di katalog yang bisa direkomendasikan."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
        db.execute(text("DELETE FROM prodi WHERE rumpun = 'Hukum'"))
        db.commit()
    app = create_app(make_settings(), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        h = muat_persona(c, "rani")
        assert "Hukum" not in {r["rumpun"] for r in ok(jelajah(c, h, top_n=10))["rekomendasi"]}


# ------------------------------------------------------------------ profesi (tabel + ingest)


def test_profesi_dari_tabel_menggantikan_contoh_umum(app_seed, clean_db: Engine):
    with Session(clean_db) as db:
        hasil = ingest(
            db,
            "profesi",
            [
                {
                    "rumpun": "Teknik",
                    "nama": "Insinyur sipil",
                    "deskripsi": "Merancang infrastruktur",
                },
                {"rumpun": "Teknik", "nama": "Insinyur industri"},
                {"rumpun": "Teknik", "nama": "Insinyur kimia"},
                {"rumpun": "Teknik", "nama": "Insinyur lingkungan"},
            ],
        )
        assert hasil.ok and hasil.ringkasan == {"profesi": 4}
    h = muat_persona(app_seed, "rani")
    rek = {r["rumpun"]: r for r in ok(jelajah(app_seed, h, top_n=10))["rekomendasi"]}
    # urut id (teknik-insinyur-industri, -kimia, -lingkungan, -sipil), dipotong maks_profesi = 3
    assert rek["Teknik"]["contoh_profesi"] == [
        "Insinyur industri",
        "Insinyur kimia",
        "Insinyur lingkungan",
    ]
    assert rek["Teknik"]["sumber_profil"]["profesi"] == "tabel_profesi"
    assert rek["Hukum"]["sumber_profil"]["profesi"] == "contoh_umum"


def test_ingest_profesi_idempoten_dan_membuat_id_dari_rumpun_dan_nama(app_seed, clean_db: Engine):
    baris = [{"rumpun": "Teknik", "nama": "Insinyur Sipil & Lingkungan"}]
    with Session(clean_db) as db:
        assert ingest(db, "profesi", baris).ok and ingest(db, "profesi", baris).ok
        (p,) = db.query(m.Profesi).all()
        assert p.id == "teknik-insinyur-sipil-lingkungan" and p.deskripsi is None
        assert ingest(db, "profesi", [{**baris[0], "deskripsi": "Baru"}]).ok
        assert db.query(m.Profesi).one().deskripsi == "Baru"


@pytest.mark.parametrize(
    "baris, pesan",
    [
        ([{"rumpun": "Teknik", "nama": ""}], "rumpun dan nama wajib"),
        ([{"rumpun": "", "nama": "X"}], "rumpun dan nama wajib"),
        ([{"rumpun": "Teknik", "nama": "X", "id": "ID Salah!"}], "id hanya boleh"),
        (
            [
                {"rumpun": "Teknik", "nama": "A", "id": "a"},
                {"rumpun": "Teknik", "nama": "B", "id": "a"},
            ],
            "duplikat",
        ),
        ([{"rumpun": "Rumpun Tak Ada", "nama": "X"}], "tidak ada di katalog prodi"),
    ],
)
def test_ingest_profesi_menolak_baris_tidak_valid_tanpa_menyimpan_apa_pun(
    app_seed, clean_db: Engine, baris, pesan
):
    with Session(clean_db) as db:
        hasil = ingest(db, "profesi", [{"rumpun": "Teknik", "nama": "Baris baik"}, *baris])
        assert not hasil.ok and any(pesan in e.pesan for e in hasil.error)
        assert db.query(m.Profesi).count() == 0  # satu tipe = satu transaksi


def test_ingest_profesi_lewat_endpoint_admin(clean_db: Engine, app_config: AppConfig):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    app = create_app(make_settings(admin_key="kunci"), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(
            "/api/v1/admin/ingest",
            headers={"X-Admin-Key": "kunci"},
            json={"tipe": "profesi", "payload": [{"rumpun": "Hukum", "nama": "Notaris"}]},
        )
        assert r.status_code == 200 and r.json()["ringkasan"] == {"profesi": 1}


def test_seed_direktori_menyertakan_profesi_bila_berkas_ada(clean_db: Engine, tmp_path: Path):
    from tests.helpers import salin_seed_terverifikasi  # noqa: F401 (memastikan helper termuat)

    seed = tmp_path / "seed"
    seed.mkdir()
    for f in SEED_DIR.glob("*.csv"):
        (seed / f.name).write_bytes(f.read_bytes())
    (seed / "profesi.csv").write_text(
        "rumpun,nama\nHukum,Notaris\nKesehatan,Dokter\n", encoding="utf-8"
    )
    with Session(clean_db) as db:
        hasil = {h.tipe: h for h in ingest_direktori(db, seed)}
        assert hasil["profesi"].ok and hasil["profesi"].ringkasan == {"profesi": 2}
        assert db.query(m.Profesi).count() == 2


# ------------------------------------------------------------------ sifat umum


def test_tanpa_llm_tanpa_penulisan_dan_tanpa_klaim_peluang(clean_db: Engine, app_config: AppConfig):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    fake = FakeLLM()
    app = create_app(make_settings(), app_config, clean_db, llm_client=fake)
    with TestClient(app, raise_server_exceptions=False) as c:
        h = muat_persona(c, "rani")

        def snap():
            with clean_db.connect() as conn:
                return [
                    [tuple(r) for r in conn.execute(text(f"SELECT * FROM {t} ORDER BY 1"))]  # noqa: S608
                    for t in ("profiles", "sessions", "strategies", "query_logs", "llm_cache")
                ]

        sebelum = snap()
        d = ok(jelajah(c, h, top_n=10, jalur="SNBT"))
        assert snap() == sebelum
    assert fake.panggilan_generate == 0 and fake.panggilan_embed == 0
    teks = [t for t in semua_teks(d) if not t.startswith("http")]
    assert not [t for t in teks if re.search(r"\d\s*%|peluang \d|probabilitas", t, re.IGNORECASE)]


# ------------------------------------------------------------------ validasi config


def ubah_config(tmp_path: Path, lama: str, baru: str) -> Path:
    isi = Path("config/app.yaml").read_text(encoding="utf-8")
    assert lama in isi
    p = tmp_path / "app.yaml"
    p.write_text(isi.replace(lama, baru, 1), encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "lama, baru, pesan",
    [
        (
            "{realistis: 0.9, investigatif: 0.8, konvensional: 0.3}",
            "{fisik: 0.9}",
            "dimensi tak dikenal: fisik",
        ),
        ("top_n_default: 5", "top_n_default: 11", "top_n_default tidak boleh melebihi top_n_maks"),
        ("bobot: {minat: 0.5, nilai: 0.5}", "bobot: {minat: 0, nilai: 0}", "harus > 0"),
        (
            "{matematika: 1.0, fisika: 1.0, kimia: 0.5}",
            "{matematika: 0, fisika: 1.0}",
            "bobot mapel harus > 0",
        ),
        (
            "{realistis: 0.9, investigatif: 0.8, konvensional: 0.3}",
            "{realistis: 1.5}",
            "bobot minat harus 0..1",
        ),
        ("maks_profesi: 3", "maks_profesi: 0", "maks_profesi"),
    ],
)
def test_config_explore_tidak_valid_gagal_cepat(tmp_path: Path, lama, baru, pesan):
    with pytest.raises(ConfigError, match=pesan):
        load_app_config(ubah_config(tmp_path, lama, baru))
