from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, get_limiter, sesi_saat_ini
from app.core.config import AppConfig
from app.core.rate_limit import SlidingWindowLimiter
from app.db.session import get_db
from app.schemas.summary import SummaryRequest
from app.services import profile, ringkasan
from app.services.sessions import SesiAktif

router = APIRouter(tags=["ringkasan"])


@router.post("/summary")
def summary(
    request: Request,
    body: SummaryRequest | None = None,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> dict:
    """Ringkasan siap cetak dari strategi tersimpan. Hanya dengan token sesi: tidak ada tautan publik.

    Narasi boleh disusun LLM (opsional) dari fakta mesin aturan. Batas LLM per sesi hanya dihitung
    saat panggilan nyata terjadi; bila terlampaui, ringkasan tetap dikembalikan dengan narasi template
    (tidak ada 429 untuk bagian yang bisa dikerjakan tanpa LLM).
    """
    ref = request.app.state.refdata.get(db)
    rows = ringkasan.pilih_strategi(db, sesi.id, body.strategy_id if body else None)
    profil = profile.baca_profil(db, sesi.id)

    def izin_llm() -> bool:
        return limiter.periksa(f"llm:{sesi.id}", config.rate_limit.llm_per_sesi) is None

    return ringkasan.susun_ringkasan(
        db,
        ref,
        config,
        sesi.id,
        profil,
        rows,
        llm=request.app.state.llm,
        izin_llm=izin_llm,
    )
