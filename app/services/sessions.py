"""Layanan sesi tamu (FR-A1 sampai A4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import buat_token, hash_token
from app.db.models import Sesi


@dataclass(frozen=True)
class SesiAktif:
    id: uuid.UUID
    consent_at: datetime
    consent_version: str
    created_at: datetime
    expires_at: datetime

    def sisa_detik(self, sekarang: datetime | None = None) -> int:
        sekarang = sekarang or datetime.now(UTC)
        return max(int((self.expires_at - sekarang).total_seconds()), 0)


def buat_sesi(db: Session, *, consent_version: str, ttl_jam: int) -> tuple[str, SesiAktif]:
    """Buat sesi baru dan kembalikan token mentah (hanya hash yang disimpan)."""
    token = buat_token()
    sekarang = datetime.now(UTC)
    baris = Sesi(
        id=uuid.uuid4(),
        token_hash=hash_token(token),
        consent_at=sekarang,
        consent_version=consent_version,
        created_at=sekarang,
        expires_at=sekarang + timedelta(hours=ttl_jam),
    )
    db.add(baris)
    db.commit()
    return token, _ke_aktif(baris)


def cari_sesi_aktif(db: Session, token: str) -> SesiAktif | None:
    baris = db.execute(
        select(Sesi).where(Sesi.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if baris is None or baris.expires_at <= datetime.now(UTC):
        return None
    return _ke_aktif(baris)


def hapus_sesi(db: Session, session_id: uuid.UUID) -> None:
    """Hapus sesi; data turunan ikut terhapus lewat FK ON DELETE CASCADE."""
    db.execute(delete(Sesi).where(Sesi.id == session_id))
    db.commit()


def hapus_kedaluwarsa(factory: sessionmaker[Session]) -> int:
    with factory() as db:
        hasil = db.execute(delete(Sesi).where(Sesi.expires_at <= datetime.now(UTC)))
        db.commit()
        return hasil.rowcount or 0


def _ke_aktif(baris: Sesi) -> SesiAktif:
    return SesiAktif(
        id=baris.id,
        consent_at=baris.consent_at,
        consent_version=baris.consent_version,
        created_at=baris.created_at,
        expires_at=baris.expires_at,
    )
