from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.db.session import get_db
from app.schemas.profile import ProfilePatch, ProfilResponse
from app.services import profile as layanan
from app.services.sessions import SesiAktif

router = APIRouter(tags=["profil"])


@router.get("/profile", response_model=ProfilResponse)
def baca(
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
) -> dict:
    ref = request.app.state.refdata.get(db)
    profil = layanan.baca_profil(db, sesi.id)
    return layanan.ke_respons(profil, layanan.hitung_data_kurang(ref, profil))


@router.put("/profile", response_model=ProfilResponse)
def perbarui(
    body: ProfilePatch,
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Simpan profil secara parsial: hanya field yang dikirim yang berubah, `null` menghapus."""
    ref = request.app.state.refdata.get(db)
    dasar = layanan.baca_profil(db, sesi.id)
    patch = body.model_dump(exclude_unset=True)
    gabungan = layanan.profil_gabungan(db, dasar, patch, config, ref)
    if patch:
        layanan.simpan_profil(db, sesi.id, gabungan)
    return layanan.ke_respons(gabungan, layanan.hitung_data_kurang(ref, gabungan))
