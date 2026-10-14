from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import batasi_buat_sesi, get_config, get_settings_app, sesi_saat_ini
from app.core.config import AppConfig, Settings
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.session import SessionCreate, SessionCreated, SessionStatus
from app.services import sessions as layanan
from app.services.sessions import SesiAktif

router = APIRouter(tags=["sesi"])


@router.post("/session", status_code=201, response_model=SessionCreated)
def buat_sesi(
    body: SessionCreate,
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
    settings: Settings = Depends(get_settings_app),
    _: None = Depends(batasi_buat_sesi),
) -> SessionCreated:
    if body.consent is not True:
        raise AppError(
            "consent_diperlukan",
            "Persetujuan (consent) wajib sebelum data apa pun diproses",
            status_code=400,
        )
    if not body.consent_version or not body.consent_version.strip():
        raise AppError(
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            status_code=422,
            detail={
                "field": [{"field": "consent_version", "pesan": "wajib diisi", "tipe": "missing"}]
            },
        )
    ttl_jam = settings.session_ttl_hours or config.sesi.ttl_jam
    token, sesi = layanan.buat_sesi(
        db, consent_version=body.consent_version.strip(), ttl_jam=ttl_jam
    )
    return SessionCreated(
        token=token,
        expires_at=sesi.expires_at,
        sisa_detik=sesi.sisa_detik(),
        pemberitahuan=config.teks.pemberitahuan_demo,
    )


@router.get("/session", response_model=SessionStatus)
def status_sesi(
    sesi: SesiAktif = Depends(sesi_saat_ini), config: AppConfig = Depends(get_config)
) -> SessionStatus:
    return SessionStatus(
        dibuat_pada=sesi.created_at,
        consent_at=sesi.consent_at,
        consent_version=sesi.consent_version,
        expires_at=sesi.expires_at,
        sisa_detik=sesi.sisa_detik(),
        pemberitahuan=config.teks.pemberitahuan_demo,
    )


@router.delete("/session", status_code=204)
def hapus_data_saya(
    sesi: SesiAktif = Depends(sesi_saat_ini), db: Session = Depends(get_db)
) -> Response:
    """'Hapus data saya': menghapus sesi dan seluruh data turunannya (FR-A4)."""
    layanan.hapus_sesi(db, sesi.id)
    return Response(status_code=204)
