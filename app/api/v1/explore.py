from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.explore import ExploreRequest
from app.services import eksplorasi, profile
from app.services.sessions import SesiAktif

router = APIRouter(tags=["eksplorasi"])


@router.post("/explore")
def explore(
    request: Request,
    body: ExploreRequest | None = None,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Rekomendasi rumpun dari minat dan nilai (deterministik, tanpa LLM)."""
    body = body or ExploreRequest()
    top_n = body.top_n or config.explore.top_n_default
    if top_n > config.explore.top_n_maks:
        raise AppError(
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            status_code=422,
            detail={
                "field": [
                    {
                        "field": "top_n",
                        "pesan": f"maksimal {config.explore.top_n_maks}",
                        "tipe": "less_than_equal",
                    }
                ]
            },
        )
    ref = request.app.state.refdata.get(db) if body.jalur else None
    return eksplorasi.jelajahi(
        db,
        ref,
        config,
        profile.baca_profil(db, sesi.id),
        top_n=top_n,
        jalur=body.jalur,
        sesi_id=sesi.id,
        draf=getattr(request.app.state, "draf", None),
    )
