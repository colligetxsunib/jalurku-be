"""Pencatatan pertanyaan (query_logs): hanya teks yang sudah disaring PII dan dipotong."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models as m
from app.llm.pii import saring_pii

log = logging.getLogger("jalurku.querylog")
PANJANG_MAKS = 500


def catat(
    db: Session,
    session_id: uuid.UUID,
    pertanyaan: str,
    *,
    yakin: bool,
    sumber_ids: Sequence[int],
) -> str:
    """Simpan pertanyaan tersaring. Mengembalikan teks yang disimpan. Kegagalan log tidak memutus jawaban."""
    bersih = saring_pii(pertanyaan).teks[:PANJANG_MAKS]
    try:
        db.add(
            m.QueryLog(
                session_id=session_id, pertanyaan=bersih, yakin=yakin, sumber_ids=list(sumber_ids)
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        log.warning("gagal mencatat query_logs")
    return bersih
