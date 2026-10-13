"""Task 15: skrip smoke test pasca-deploy (diuji terhadap aplikasi in-process)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.ingest.service import ingest_direktori
from app.main import create_app
from scripts.smoke_test import cetak, jalankan
from tests.conftest import make_settings
from tests.helpers import SEED_DIR

KUNCI_ADMIN = "kunci-admin-uji"


@pytest.fixture()
def app_prod(clean_db: Engine, app_config: AppConfig) -> Iterator[TestClient]:
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    app = create_app(make_settings(app_env="prod", admin_key=KUNCI_ADMIN), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.db
def test_semua_pemeriksaan_lulus_di_produksi(app_prod):
    hasil = jalankan(app_prod, prod=True, admin_key=KUNCI_ADMIN)
    gagal = [h for h in hasil if not h.ok]
    assert not gagal, gagal
    nama = {h.nama for h in hasil}
    assert {"POST /analyze", "POST /strategy", "POST /summary", "POST /query"} <= nama
    assert cetak(hasil) == 0


@pytest.mark.db
def test_setiap_persona_lulus(app_prod):
    for persona in ("rani", "dimas", "budi", "sinta"):
        hasil = jalankan(app_prod, persona=persona, prod=True)
        assert all(h.ok for h in hasil), (persona, [h for h in hasil if not h.ok])


@pytest.mark.db
def test_kunci_admin_salah_terdeteksi(app_prod):
    hasil = jalankan(app_prod, prod=True, admin_key="bukan-kunci-sebenarnya")
    admin = next(h for h in hasil if h.nama.startswith("POST /admin/ingest"))
    assert not admin.ok


@pytest.mark.db
def test_docs_terbuka_di_dev_terdeteksi(clean_db, app_config):
    with Session(clean_db) as db:
        ingest_direktori(db, SEED_DIR)
    app = create_app(make_settings(app_env="dev"), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        hasil = jalankan(c, prod=True)  # prod=True menuntut /docs mati; dev membukanya
    docs = next(h for h in hasil if h.nama.startswith("dokumentasi API"))
    assert not docs.ok
    assert cetak(hasil) == 1


@pytest.mark.db
def test_lewat_proxy_gagal_tanpa_header_nginx(app_prod):
    """Aplikasi langsung (tanpa nginx) tidak mengirim header keamanan proxy: harus terdeteksi."""
    hasil = jalankan(app_prod, prod=True, lewat_proxy=True)
    assert not next(h for h in hasil if h.nama == "header keamanan nginx").ok


def test_berhenti_bila_server_tidak_hidup(client_no_db):
    hasil = jalankan(client_no_db)
    assert [h.nama for h in hasil] == ["GET /health"]
    assert not hasil[0].ok
    assert cetak(hasil) == 1
