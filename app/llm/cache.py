"""Cache respons LLM dan embedding pertanyaan di tabel `llm_cache` (best-effort).

Kunci = hash dari (namespace, model, input deterministik yang BEBAS PII). Kegagalan cache tidak boleh
menggagalkan permintaan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import LlmCache

log = logging.getLogger("jalurku.llm.cache")


def buat_kunci(namespace: str, model: str, masukan: Mapping[str, Any] | str) -> str:
    baku = json.dumps(
        {"ns": namespace, "model": model, "in": masukan},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(baku.encode("utf-8")).hexdigest()


def ambil(db: Session, kunci: str, *, sekarang: datetime | None = None) -> Any | None:
    """Kembalikan isi cache yang belum kedaluwarsa, atau None."""
    sekarang = sekarang or datetime.now(UTC)
    try:
        baris = db.execute(select(LlmCache).where(LlmCache.key_hash == kunci)).scalar_one_or_none()
    except SQLAlchemyError:
        db.rollback()
        log.warning("cache: gagal membaca")
        return None
    if baris is None:
        return None
    if baris.created_at + timedelta(seconds=baris.ttl_detik) <= sekarang:
        return None
    return baris.respons


def simpan(db: Session, kunci: str, respons: Any, ttl_detik: int) -> None:
    """Upsert. ttl_detik <= 0 berarti cache dimatikan."""
    if ttl_detik <= 0:
        return
    try:
        db.execute(
            text(
                "INSERT INTO llm_cache (key_hash, respons, created_at, ttl_detik) "
                "VALUES (:k, CAST(:r AS jsonb), now(), :t) "
                "ON CONFLICT (key_hash) DO UPDATE SET respons = EXCLUDED.respons, "
                "created_at = now(), ttl_detik = EXCLUDED.ttl_detik"
            ),
            {"k": kunci, "r": json.dumps(respons, ensure_ascii=False), "t": ttl_detik},
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        log.warning("cache: gagal menyimpan")


def hapus_kedaluwarsa(factory: sessionmaker[Session]) -> int:
    with factory() as db:
        hasil = db.execute(
            text(
                "DELETE FROM llm_cache WHERE created_at + make_interval(secs => ttl_detik) <= now()"
            )
        )
        db.commit()
        return hasil.rowcount or 0
