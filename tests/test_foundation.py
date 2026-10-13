"""Task 1: config fail-fast, format error standar, health."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import ConfigError, load_app_config
from app.core.errors import AppError
from app.main import create_app
from tests.conftest import make_settings


def test_config_repo_valid(app_config):
    assert app_config.embedding.model == "gemini-embedding-001"
    assert app_config.embedding.dimensi == 768


def test_config_berkas_tidak_ada(tmp_path: Path):
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        load_app_config(tmp_path / "tidak-ada.yaml")


def test_config_kunci_tak_dikenal_gagal(tmp_path: Path):
    isi = Path("config/app.yaml").read_text(encoding="utf-8") + "\nkunci_salah_ketik: 1\n"
    p = tmp_path / "app.yaml"
    p.write_text(isi, encoding="utf-8")
    with pytest.raises(ConfigError, match="kunci_salah_ketik"):
        load_app_config(p)


def test_config_nilai_tidak_valid_gagal(tmp_path: Path):
    isi = Path("config/app.yaml").read_text(encoding="utf-8").replace("top_k: 4", "top_k: 0")
    p = tmp_path / "app.yaml"
    p.write_text(isi, encoding="utf-8")
    with pytest.raises(ConfigError, match="rag.top_k"):
        load_app_config(p)


def test_health_503_bila_db_mati(client_no_db: TestClient):
    r = client_no_db.get("/api/v1/health")
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["kode"] == "dependensi_tidak_tersedia"
    assert set(body["error"]) == {"kode", "pesan", "detail"}


@pytest.mark.db
def test_health_200(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_404_memakai_format_standar(client_no_db: TestClient):
    r = client_no_db.get("/api/v1/tidak-ada")
    assert r.status_code == 404
    assert r.json()["error"]["kode"] == "tidak_ditemukan"


class _Body(BaseModel):
    angka: int


_uji_router = APIRouter()


@_uji_router.post("/uji")
def _uji(b: _Body):  # pragma: no cover - tubuh tidak dijalankan
    return b


@_uji_router.get("/meledak")
def _meledak():
    raise AppError("kode_uji", "pesan uji", status_code=409, detail={"a": 1})


def test_422_dibungkus_format_standar_tanpa_nilai_input(app_config):
    app = create_app(make_settings(), app_config)
    app.include_router(_uji_router)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/uji", json={"angka": "rahasia-pii"})
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["kode"] == "validasi_gagal"
        assert err["detail"]["field"][0]["field"] == "angka"
        assert "rahasia-pii" not in r.text

        r2 = c.get("/meledak")
        assert r2.status_code == 409
        assert r2.json() == {
            "error": {"kode": "kode_uji", "pesan": "pesan uji", "detail": {"a": 1}}
        }


def test_docs_dimatikan_di_prod(app_config):
    app = create_app(make_settings(app_env="prod"), app_config)
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/docs").status_code == 404
        assert c.get("/openapi.json").status_code == 404


def test_trusted_proxies_env_menimpa_yaml(app_config):
    app = create_app(make_settings(trusted_proxies="172.30.0.0/24, 10.0.0.5"), app_config)
    assert app.state.config.rate_limit.proxy_tepercaya == ["172.30.0.0/24", "10.0.0.5"]
    # config asli tidak berubah (model_copy, bukan mutasi)
    assert app_config.rate_limit.proxy_tepercaya != ["172.30.0.0/24", "10.0.0.5"]


def test_trusted_proxies_kosong_memakai_yaml(app_config):
    app = create_app(make_settings(trusted_proxies=""), app_config)
    assert app.state.config.rate_limit.proxy_tepercaya == app_config.rate_limit.proxy_tepercaya


def test_trusted_proxies_tidak_valid_gagal_start(app_config):
    with pytest.raises(ConfigError, match="TRUSTED_PROXIES"):
        create_app(make_settings(trusted_proxies="bukan-ip"), app_config)
