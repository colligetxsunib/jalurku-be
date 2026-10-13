"""Endpoint internal kurasi data (FR-D1, FR-D2). Dijaga X-Admin-Key, BUKAN token sesi."""

from __future__ import annotations

import hmac
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_config, get_limiter, get_settings_app
from app.core.config import AppConfig, Settings
from app.core.errors import AppError
from app.core.rate_limit import SlidingWindowLimiter, ip_klien, terapkan
from app.db.models import DokumenSumber
from app.db.session import get_db
from app.ingest.service import ingest
from app.llm.errors import LLMError
from app.rag.chunking import ChunkTerlaluBesar
from app.rag.extract import TanpaTeks
from app.rag.ingest import ingest_dokumen
from app.schemas.admin import IngestRequest

router = APIRouter(prefix="/admin", tags=["admin"])


def admin_terotorisasi(
    request: Request,
    x_admin_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_app),
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> None:
    if not settings.admin_key:  # ADMIN_KEY tidak diset: endpoint dianggap tidak ada
        raise AppError("tidak_ditemukan", "Sumber daya tidak ditemukan", status_code=404)
    ip = ip_klien(request, config.rate_limit.proxy_tepercaya)
    terapkan(limiter, f"admin:{ip}", config.rate_limit.per_ip)  # tumpulkan tebakan key
    if not x_admin_key or not hmac.compare_digest(
        x_admin_key.encode("utf-8"), settings.admin_key.encode("utf-8")
    ):
        raise AppError(
            "admin_key_salah",
            "X-Admin-Key tidak ada atau salah",
            status_code=401,
            headers={"WWW-Authenticate": "X-Admin-Key"},
        )


MAKS_UNGGAH_BYTE = 30 * 1024 * 1024
_ID_DOKUMEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


@router.post("/dokumen/{dokumen_id}/berkas")
def unggah_berkas_dokumen(
    dokumen_id: str,
    request: Request,
    berkas: UploadFile = File(...),
    proses: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_app),
    config: AppConfig = Depends(get_config),
    _: None = Depends(admin_terotorisasi),
) -> dict:
    """Unggah PDF sumber RAG (multipart). `proses=true` langsung memotong dan meng-embed (memakai kuota API)."""
    if not _ID_DOKUMEN.match(dokumen_id) or db.get(DokumenSumber, dokumen_id) is None:
        raise AppError(
            "dokumen_tidak_terdaftar",
            f"dokumen_id '{dokumen_id}' belum terdaftar. Ingest dokumen_rag_metadata dulu.",
            status_code=404,
        )
    isi = berkas.file.read(MAKS_UNGGAH_BYTE + 1)
    if len(isi) > MAKS_UNGGAH_BYTE:
        raise AppError("berkas_terlalu_besar", "Berkas melebihi 30 MB", status_code=413)
    if not isi.startswith(b"%PDF-"):
        raise AppError(
            "bukan_pdf",
            "Berkas bukan PDF yang valid (header %PDF- tidak ditemukan)",
            status_code=422,
        )

    folder = Path(settings.dokumen_dir)
    folder.mkdir(parents=True, exist_ok=True)
    tujuan = folder / f"{dokumen_id}.pdf"
    sementara = tujuan.with_suffix(".pdf.tmp")
    sementara.write_bytes(isi)
    os.replace(sementara, tujuan)  # atomik: tidak ada berkas setengah tertulis

    hasil: dict = {
        "dokumen_id": dokumen_id,
        "berkas": tujuan.name,
        "ukuran_byte": len(isi),
        "diterima": 1,
        "error": [],
        "proses": None,
    }
    if proses:
        try:
            r = ingest_dokumen(db, request.app.state.llm.client, config, dokumen_id, folder)
            hasil["proses"] = {
                "jumlah_chunk": r.jumlah_chunk,
                "di_embed": r.di_embed,
                "tidak_berubah": r.tidak_berubah,
                "dihapus": r.dihapus,
            }
        except (TanpaTeks, ChunkTerlaluBesar, ValueError) as exc:
            hasil["error"].append({"sumber": dokumen_id, "baris": 0, "pesan": str(exc)})
        except LLMError as exc:
            hasil["error"].append(
                {
                    "sumber": dokumen_id,
                    "baris": 0,
                    "pesan": f"embedding gagal ({type(exc).__name__}); berkas tersimpan",
                }
            )
    return hasil


@router.post("/ingest")
def ingest_data(
    body: IngestRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_app),
    _: None = Depends(admin_terotorisasi),
) -> dict:
    hasil = ingest(db, body.tipe, body.payload, require_verified=settings.require_verified)
    if hasil.error:
        raise AppError(
            "impor_ditolak",
            f"Impor ditolak: {len(hasil.error)} baris bermasalah. Tidak ada data yang tersimpan.",
            status_code=422,
            detail=hasil.ke_dict(),
        )
    request.app.state.refdata.invalidate()
    return hasil.ke_dict()
