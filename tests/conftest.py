"""Fixture bersama. Tes bertanda `db` membutuhkan PostgreSQL + pgvector (docker compose up -d db)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import AppConfig, Settings, load_app_config
from app.db.models import Base
from app.db.session import make_engine
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_URL = "postgresql+psycopg://jalurku:jalurku@127.0.0.1:5433/jalurku_test"


def alembic_config(connection=None, url: str | None = None) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "app" / "db" / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)


@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    return load_app_config(Settings(_env_file=None).app_config_path)


@pytest.fixture(scope="session")
def db_engine(test_database_url: str) -> Iterator[Engine]:
    """Engine ke DB uji yang sudah dimigrasi ke head."""
    engine = make_engine(test_database_url, connect_timeout=2)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL tidak tersedia di TEST_DATABASE_URL: {type(exc).__name__}")
    with engine.begin() as conn:
        command.upgrade(alembic_config(connection=conn), "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def clean_db(db_engine: Engine) -> Engine:
    """Kosongkan semua tabel sebelum tes (data uji tidak saling bocor)."""
    tabel = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tabel} RESTART IDENTITY CASCADE"))
    return db_engine


@pytest.fixture()
def app_seed(clean_db: Engine, app_config: AppConfig) -> Iterator[TestClient]:
    """Aplikasi dengan seed lengkap (ketentuan, rules, katalog UI, dokumen) sudah dimuat."""
    from sqlalchemy.orm import Session

    from app.ingest.service import ingest_direktori

    with Session(clean_db) as db:
        hasil = ingest_direktori(db, ROOT / "data" / "seed")
        assert all(h.ok for h in hasil), [e for h in hasil for e in h.error]
    app = create_app(make_settings(), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def make_settings(**overrides) -> Settings:
    base = {
        "database_url": DEFAULT_TEST_URL,
        "gemini_api_key": "",
        "admin_key": "",
        "cors_origins": "",
        "require_verified": False,
        "app_env": "dev",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture()
def client_no_db(app_config: AppConfig) -> Iterator[TestClient]:
    """Aplikasi yang DB-nya tidak bisa dijangkau (port tertutup)."""
    engine = make_engine("postgresql+psycopg://x:y@127.0.0.1:1/z", connect_timeout=1)
    app = create_app(make_settings(), app_config, engine)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def client(clean_db: Engine, app_config: AppConfig) -> Iterator[TestClient]:
    app = create_app(make_settings(), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
