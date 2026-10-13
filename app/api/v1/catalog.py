from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import sesi_saat_ini
from app.core.errors import AppError
from app.db.session import get_db
from app.domain.provinsi import normalisasi_provinsi
from app.services import katalog
from app.services.katalog import Halaman
from app.services.sessions import SesiAktif

router = APIRouter(prefix="/catalog", tags=["katalog"])

Page = Annotated[int, Query(ge=1, le=100000, description="Nomor halaman, mulai 1")]
Limit = Annotated[int, Query(ge=1, le=100, description="Jumlah item per halaman (maks 100)")]
Teks = Annotated[str | None, Query(max_length=100)]


def _provinsi(nilai: str | None) -> str | None:
    if nilai is None or not nilai.strip():
        return None
    baku = normalisasi_provinsi(nilai)
    if baku is None:
        raise AppError(
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            status_code=422,
            detail={
                "field": [
                    {"field": "provinsi", "pesan": "bukan provinsi baku", "tipe": "value_error"}
                ]
            },
        )
    return baku


@router.get("/ptn")
def daftar_ptn(
    q: Teks = None,
    provinsi: Teks = None,
    page: Page = 1,
    limit: Limit = 20,
    _: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
) -> dict:
    return katalog.daftar_ptn(db, q=q, provinsi=_provinsi(provinsi), h=Halaman(page, limit))


@router.get("/prodi")
def daftar_prodi(
    q: Teks = None,
    rumpun: Teks = None,
    provinsi: Teks = None,
    jalur: Literal["SNBP", "SNBT"] | None = None,
    ptn_id: Teks = None,
    program: Literal["akademik", "vokasi"] | None = None,
    jenjang: Literal["S1", "D3", "D4"] | None = None,
    page: Page = 1,
    limit: Limit = 20,
    _: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
) -> dict:
    return katalog.daftar_prodi(
        db,
        q=q,
        rumpun=rumpun,
        provinsi=_provinsi(provinsi),
        jalur=jalur,
        ptn_id=ptn_id,
        program=program,
        jenjang=jenjang,
        h=Halaman(page, limit),
    )


@router.get("/prodi/{prodi_id}")
def detail_prodi(
    prodi_id: str,
    _: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
) -> dict:
    return katalog.detail_prodi(db, prodi_id)
