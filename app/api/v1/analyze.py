from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.db.session import get_db
from app.schemas.analyze import AnalyzeRequest
from app.services import analisis, profile
from app.services.sessions import SesiAktif

router = APIRouter(tags=["analisis"])


@router.post("/analyze")
def analyze(
    body: AnalyzeRequest,
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Gate lalu penilaian per target per jalur. `override` menghitung ulang tanpa menyimpan."""
    ref = request.app.state.refdata.get(db)
    dasar = profile.baca_profil(db, sesi.id)
    patch = body.override.model_dump(exclude_unset=True) if body.override else {}
    profil = profile.profil_gabungan(db, dasar, patch, config, ref)  # tidak ditulis ke DB
    targets = [(t.prodi_id, t.jalur) for t in body.targets]
    return {"hasil": analisis.analisis_banyak(db, ref, config, profil, targets)}
