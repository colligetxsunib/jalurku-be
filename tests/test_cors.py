"""CORS: origin dev localhost:4173 diizinkan bila terdaftar; origin produksi tetap jalan.

Latar: frontend dev di http://localhost:4173 kena blokir preflight karena origin itu tidak ada di
CORS_ORIGINS produksi. Mekanisme (CORSMiddleware + daftar eksplisit dari env) sudah benar; yang
kurang hanya entrinya. Tes ini mengunci perilaku mekanisme tersebut tanpa menyentuh nilai
produksi: dev lolos bila terdaftar, produksi tetap lolos, tak terdaftar tetap ditolak.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

pytestmark = pytest.mark.db

PROD = "https://jalurku-ui.contoh.id"
DEV = "http://localhost:4173"
DEV_IP = "http://127.0.0.1:4173"
ASING = "https://evil.contoh.id"
TARGET = "/api/v1/riasec/questions"  # endpoint publik tempat laporan berasal


@pytest.fixture()
def app_cors(clean_db, app_config):
    origins = ",".join([PROD, DEV, DEV_IP])
    app = create_app(make_settings(cors_origins=origins), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _preflight(c: TestClient, origin: str):
    return c.options(
        TARGET,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )


@pytest.mark.parametrize("origin", [DEV, DEV_IP])
def test_preflight_origin_dev_berhasil(app_cors, origin):
    r = _preflight(app_cors, origin)
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == origin
    assert "GET" in r.headers.get("access-control-allow-methods", "")
    izinkan = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in izinkan and "content-type" in izinkan


def test_preflight_origin_produksi_tetap_berhasil(app_cors):
    r = _preflight(app_cors, PROD)
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == PROD


def test_preflight_origin_tak_terdaftar_tanpa_header_acao(app_cors):
    r = _preflight(app_cors, ASING)
    assert "access-control-allow-origin" not in r.headers


def test_get_asli_origin_dev_membawa_acao(app_cors):
    r = app_cors.get(TARGET, headers={"Origin": DEV})
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == DEV


def test_tanpa_daftar_origin_tidak_ada_header_acao(client):
    r = client.options(
        TARGET,
        headers={
            "Origin": DEV,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in r.headers
