from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    """Consent dicek manual di endpoint agar kegagalannya selalu 400 `consent_diperlukan`."""

    model_config = ConfigDict(extra="forbid")

    consent: bool = False
    consent_version: str | None = Field(default=None, max_length=32)


class SessionCreated(BaseModel):
    token: str
    expires_at: datetime
    sisa_detik: int
    pemberitahuan: str  # catatan "demo memakai data fiktif" untuk ditampilkan di UI


class SessionStatus(BaseModel):
    aktif: bool = True
    dibuat_pada: datetime
    consent_at: datetime
    consent_version: str
    expires_at: datetime
    sisa_detik: int
    pemberitahuan: str
