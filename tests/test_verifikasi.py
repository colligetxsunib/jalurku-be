"""Task 17: REQUIRE_VERIFIED menolak start bila tabel kritis memuat data tanpa tanggal verifikasi."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import AppConfig, ConfigError
from app.db import models as m
from app.db.verifikasi import (
    cari_belum_terverifikasi,
    hitung_per_tabel,
    pastikan_terverifikasi,
    ringkas_per_tabel,
)
from app.ingest.service import ingest, ingest_direktori
from app.main import create_app
from scripts import check_verified
from tests.conftest import DEFAULT_TEST_URL, make_settings
from tests.helpers import SEED_DIR, salin_seed_terverifikasi

pytestmark = pytest.mark.db


def muat(engine: Engine, direktori: Path, **kw) -> None:
    with Session(engine) as db:
        hasil = ingest_direktori(db, direktori, **kw)
        assert all(h.ok for h in hasil), [e for h in hasil for e in h.error]


def start(engine: Engine, config: AppConfig, **settings) -> None:
    app = create_app(make_settings(**settings), config, engine)
    with TestClient(app):  # startup (lifespan) berjalan di sini
        pass


# ------------------------------------------------------------------ pemeriksaan data


def test_db_kosong_tidak_ada_temuan(clean_db: Engine):
    with Session(clean_db) as db:
        assert cari_belum_terverifikasi(db, lengkap=True) == []
        pastikan_terverifikasi(db)  # tabel kosong lolos: urutan deploy "naik dulu, ingest kemudian"


def test_seed_apa_adanya_belum_terverifikasi(clean_db: Engine):
    muat(clean_db, SEED_DIR)
    with Session(clean_db) as db:
        per_tabel = ringkas_per_tabel(cari_belum_terverifikasi(db))
        assert per_tabel == {"rules_jalur": 2, "ketentuan": 22}  # acuan_skor kosong
        lengkap = ringkas_per_tabel(cari_belum_terverifikasi(db, lengkap=True))
        assert lengkap["ptn"] == 10 and lengkap["prodi"] == 185 and lengkap["prodi_jalur"] == 31
        with pytest.raises(ConfigError, match="rules_jalur: 2, ketentuan: 22"):
            pastikan_terverifikasi(db)


def test_pesan_error_memberi_jalan_keluar(clean_db: Engine):
    muat(clean_db, SEED_DIR)
    with Session(clean_db) as db, pytest.raises(ConfigError) as e:
        pastikan_terverifikasi(db)
    pesan = str(e.value)
    assert "REQUIRE_VERIFIED=true" in pesan and "scripts.check_verified" in pesan
    assert "rules_jalur/SNBP-2026" in pesan or "rules_jalur/SNBT-2026" in pesan


def test_data_kritis_terverifikasi_lolos_walau_katalog_belum(clean_db: Engine, tmp_path: Path):
    muat(clean_db, salin_seed_terverifikasi(tmp_path / "seed"))
    with Session(clean_db) as db:
        pastikan_terverifikasi(db)
        assert cari_belum_terverifikasi(db) == []
        assert ringkas_per_tabel(cari_belum_terverifikasi(db, lengkap=True))["prodi"] == 185


def test_satu_dokumen_wajib_tanpa_tanggal_membuat_rule_belum_terverifikasi(
    clean_db: Engine, tmp_path: Path
):
    muat(clean_db, salin_seed_terverifikasi(tmp_path / "seed"))
    with Session(clean_db) as db:
        rule = db.get(m.RulesJalur, "SNBT-2026")
        rule.dokumen_wajib = [
            {**d, "terakhir_diverifikasi": None} if i == 0 else d
            for i, d in enumerate(rule.dokumen_wajib)
        ]
        db.commit()
        temuan = cari_belum_terverifikasi(db)
        assert [(t.tabel, t.kunci) for t in temuan] == [("rules_jalur", "SNBT-2026")]
        assert "1 dari 8 dokumen wajib" in temuan[0].alasan


def test_acuan_skor_tanpa_tanggal_terdeteksi(clean_db: Engine, tmp_path: Path):
    muat(clean_db, salin_seed_terverifikasi(tmp_path / "seed"))
    with Session(clean_db) as db:
        assert ingest(
            db,
            "acuan",
            [
                {
                    "prodi_id": "ui-ilmu-komputer",
                    "jalur": "SNBT",
                    "rendah": "660",
                    "tinggi": "720",
                    "tahun": "2025",
                    "sumber_url": "https://contoh.id/a",
                }
            ],
        ).ok
        temuan = cari_belum_terverifikasi(db)
        assert [(t.tabel, t.kunci) for t in temuan] == [
            ("acuan_skor", "ui-ilmu-komputer|SNBT|2025")
        ]
        assert hitung_per_tabel(db)["acuan_skor"] == (1, 1)


# ------------------------------------------------------------------ guard startup


def test_start_ditolak_bila_require_verified_dan_ada_data_belum_terverifikasi(
    clean_db: Engine, app_config: AppConfig
):
    muat(clean_db, SEED_DIR)
    with pytest.raises(ConfigError, match="REQUIRE_VERIFIED"):
        start(clean_db, app_config, require_verified=True)


def test_start_boleh_bila_require_verified_mati(clean_db: Engine, app_config: AppConfig):
    muat(clean_db, SEED_DIR)
    start(clean_db, app_config, require_verified=False)


def test_start_boleh_bila_semua_data_kritis_terverifikasi(
    clean_db: Engine, app_config: AppConfig, tmp_path: Path
):
    muat(clean_db, salin_seed_terverifikasi(tmp_path / "seed"))
    start(clean_db, app_config, require_verified=True)


def test_start_boleh_dengan_db_kosong(clean_db: Engine, app_config: AppConfig):
    start(clean_db, app_config, require_verified=True)


def test_start_ditolak_karena_satu_acuan_saja(
    clean_db: Engine, app_config: AppConfig, tmp_path: Path
):
    muat(clean_db, salin_seed_terverifikasi(tmp_path / "seed"))
    with Session(clean_db) as db:
        db.add(
            m.AcuanSkor(
                prodi_id="ui-ilmu-komputer", jalur="SNBT", tahun=2025, rendah=600, tinggi=700
            )
        )
        db.commit()
    with pytest.raises(ConfigError, match="acuan_skor: 1"):
        start(clean_db, app_config, require_verified=True)


def test_db_tidak_terjangkau_tidak_menggagalkan_start_tetapi_health_503(
    client_no_db: TestClient, app_config: AppConfig
):
    """Guard dilewati (dengan peringatan) bila DB mati; /health yang melaporkan masalahnya."""
    engine = client_no_db.app.state.engine
    app = create_app(make_settings(require_verified=True), app_config, engine)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/api/v1/health").status_code == 503


def test_ingest_admin_menolak_baris_tanpa_tanggal_saat_require_verified(
    clean_db: Engine, app_config: AppConfig
):
    app = create_app(make_settings(require_verified=True, admin_key="k"), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(
            "/api/v1/admin/ingest",
            headers={"X-Admin-Key": "k"},
            json={
                "tipe": "ketentuan",
                "payload": [
                    {
                        "key": "max_pilihan_prodi",
                        "jalur": "SNBP",
                        "tahun_siklus": "2026",
                        "nilai": "2",
                        "sumber_url": "https://contoh.id/x",
                    }
                ],
            },
        )
    assert r.status_code == 422
    with Session(clean_db) as db:
        assert db.query(m.Ketentuan).count() == 0


# ------------------------------------------------------------------ skrip check_verified


def test_check_verified_gagal_dan_menjelaskan(clean_db: Engine, capsys: pytest.CaptureFixture):
    muat(clean_db, SEED_DIR)
    kode = check_verified.main(["--database-url", DEFAULT_TEST_URL, "--detail"])
    keluar = capsys.readouterr().out
    assert kode == 1
    assert "[BELUM  ] rules_jalur" in keluar and "0/22 terverifikasi" in keluar
    assert "Persona demo" in keluar and "BELUM SIAP" in keluar
    assert "hanya 12 pertanyaan (minimal 20)" in keluar


def test_check_verified_tidak_mengubah_data(clean_db: Engine):
    muat(clean_db, SEED_DIR)

    def isi() -> list[tuple]:
        with clean_db.connect() as conn:
            return [
                tuple(r)
                for t in ("rules_jalur", "ketentuan", "prodi")
                for r in conn.execute(text(f"SELECT * FROM {t} ORDER BY 1"))  # noqa: S608
            ]

    sebelum = isi()
    check_verified.main(["--database-url", DEFAULT_TEST_URL])
    assert isi() == sebelum  # tanggal verifikasi tidak pernah terisi otomatis
