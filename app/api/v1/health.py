from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Cek DB saja. Sengaja tidak memanggil LLM agar tidak membuang kuota."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise AppError(
            "dependensi_tidak_tersedia", "Database tidak dapat dijangkau", status_code=503
        ) from exc
    return {"status": "ok"}
