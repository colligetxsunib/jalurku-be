from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import batasi_llm, get_config
from app.core.config import AppConfig
from app.db.session import get_db
from app.schemas.query import QueryRequest
from app.services import query as layanan
from app.services.sessions import SesiAktif

router = APIRouter(tags=["tanya-jawab"])


@router.post("/query")
def query(
    body: QueryRequest,
    request: Request,
    sesi: SesiAktif = Depends(batasi_llm),  # token sesi + batas lebih ketat untuk endpoint ber-LLM
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """RAG bersitasi (`mode: tanya`) atau penjelasan hasil mesin aturan (`mode: jelaskan`).

    Klien hanya mengirim pertanyaan + identifier konteks; profil dan hasil analisis dibangun server.
    """
    return layanan.jawab(
        db,
        llm=request.app.state.llm,
        refdata=request.app.state.refdata,
        config=config,
        sesi=sesi,
        body=body,
    )
