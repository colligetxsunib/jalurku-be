from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.db.session import get_db
from app.schemas.riasec import (
    RiasecQuestionsResponse,
    RiasecResultResponse,
    RiasecSubmitRequest,
)
from app.services import riasec
from app.services.sessions import SesiAktif

router = APIRouter(tags=["minat"])


@router.get("/riasec/questions", response_model=RiasecQuestionsResponse)
def pertanyaan(
    config: AppConfig = Depends(get_config),
) -> dict:
    """Instrumen tes minat RIASEC untuk ditampilkan (FR-E2). Publik: tidak memuat data sesi."""
    return riasec.pertanyaan(config)


@router.post("/riasec/submit", response_model=RiasecResultResponse)
def submit(
    body: RiasecSubmitRequest,
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Skor jawaban jadi vektor minat (deterministik). `simpan=True` menulis ke profil → dipakai /explore."""
    ref = request.app.state.refdata.get(db)
    return riasec.nilai(db, sesi.id, body.jawaban, config, ref, simpan=body.simpan)
