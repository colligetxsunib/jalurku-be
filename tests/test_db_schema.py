"""Task 2: migrasi up/down, cascade hapus sesi, guard embedding."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session

from app.core.config import AppConfig, ConfigError
from app.db.guards import check_embedding_consistency
from app.db.models import (
    EMBEDDING_DIM,
    Base,
    DokumenSumber,
    Profil,
    QueryLog,
    RagChunk,
    Sesi,
    Strategi,
)
from app.db.session import make_engine
from tests.conftest import alembic_config

pytestmark = pytest.mark.db


def _tabel(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        ).scalars()
        return set(rows)


@pytest.fixture()
def scratch_engine(test_database_url: str, db_engine: Engine) -> Iterator[Engine]:
    """Database sementara (kosong) untuk tes migrasi dan guard."""
    nama = f"jalurku_scratch_{uuid.uuid4().hex[:8]}"
    url = make_url(test_database_url)
    admin = make_engine(url.set(database="postgres").render_as_string(hide_password=False))
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{nama}"'))
    engine = make_engine(url.set(database=nama).render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{nama}" WITH (FORCE)'))
        admin.dispose()


def _migrate(engine: Engine, target: str = "head") -> None:
    with engine.begin() as conn:
        command.upgrade(alembic_config(connection=conn), target)


def test_migrasi_up_down_up(scratch_engine: Engine):
    harapan = {t.name for t in Base.metadata.sorted_tables}
    _migrate(scratch_engine)
    assert harapan <= _tabel(scratch_engine)

    with scratch_engine.begin() as conn:
        command.downgrade(alembic_config(connection=conn), "base")
    assert not (harapan & _tabel(scratch_engine))

    _migrate(scratch_engine)
    assert harapan <= _tabel(scratch_engine)


def test_kolom_embedding_768(scratch_engine: Engine):
    _migrate(scratch_engine)
    assert EMBEDDING_DIM == 768
    with scratch_engine.connect() as conn:
        dim = conn.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'rag_chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar()
    assert dim == 768


def test_hapus_sesi_menghapus_semua_data_turunan(clean_db: Engine):
    sid = uuid.uuid4()
    sekarang = datetime.now(UTC)
    with Session(clean_db) as s:
        s.add(
            Sesi(
                id=sid,
                token_hash="a" * 64,
                consent_at=sekarang,
                consent_version="2026-10-13",
                expires_at=sekarang + timedelta(hours=24),
            )
        )
        s.flush()
        s.add(Profil(session_id=sid, tahun_lulus=2026))
        s.add(Strategi(session_id=sid, jalur="SNBT", pilihan=[], hasil_evaluasi={}))
        s.add(QueryLog(session_id=sid, pertanyaan="uji", yakin=False, sumber_ids=[]))
        s.commit()

    with Session(clean_db) as s:
        s.delete(s.get(Sesi, sid))
        s.commit()

    with clean_db.connect() as conn:
        for tabel in ("profiles", "strategies", "query_logs"):
            n = conn.execute(
                text(f"SELECT count(*) FROM {tabel} WHERE session_id = :sid"), {"sid": sid}
            ).scalar()
            assert n == 0, tabel


def test_guard_lolos_pada_config_sesuai(scratch_engine: Engine, app_config: AppConfig):
    _migrate(scratch_engine)
    check_embedding_consistency(scratch_engine, app_config)


def test_guard_gagal_bila_tabel_belum_ada(scratch_engine: Engine, app_config: AppConfig):
    with pytest.raises(ConfigError, match="alembic upgrade head"):
        check_embedding_consistency(scratch_engine, app_config)


def test_guard_gagal_bila_dimensi_beda(scratch_engine: Engine, app_config: AppConfig):
    _migrate(scratch_engine)
    salah = app_config.model_copy(
        update={"embedding": app_config.embedding.model_copy(update={"dimensi": 1536})}
    )
    with pytest.raises(ConfigError, match="Dimensi embedding"):
        check_embedding_consistency(scratch_engine, salah)


def test_guard_gagal_bila_model_chunk_beda(scratch_engine: Engine, app_config: AppConfig):
    _migrate(scratch_engine)
    with Session(scratch_engine) as s:
        s.add(DokumenSumber(id="d1", judul="J", url="u", jenis="uji", tahun_siklus=2026))
        s.flush()
        s.add(
            RagChunk(
                dokumen_id="d1",
                urutan=0,
                teks="x",
                embedding=[0.0] * EMBEDDING_DIM,
                embedding_model="model-lain",
                sumber_url="u",
                tahun_siklus=2026,
            )
        )
        s.commit()
    with pytest.raises(ConfigError, match="model-lain"):
        check_embedding_consistency(scratch_engine, app_config)
