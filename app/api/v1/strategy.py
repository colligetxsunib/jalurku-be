from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.db.session import get_db
from app.schemas.strategy import StrategyRequest
from app.services import profile, strategi
from app.services.sessions import SesiAktif

router = APIRouter(tags=["strategi"])


@router.post("/strategy")
def strategy(
    body: StrategyRequest,
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Evaluasi komposisi pilihan satu jalur + saran swap dari shortlist.

    `override` = what-if: hitung ulang tanpa menyimpan apa pun, dan `simpan` dipaksa false.
    """
    ref = request.app.state.refdata.get(db)
    dasar = profile.baca_profil(db, sesi.id)
    patch = body.override.model_dump(exclude_unset=True) if body.override is not None else {}
    profil = profile.profil_gabungan(db, dasar, patch, config, ref)  # tidak ditulis ke DB

    pilihan_ids = [p.prodi_id for p in body.pilihan]
    hasil = strategi.evaluasi_strategi(
        db, ref, config, sesi.id, profil, body.jalur, pilihan_ids, body.shortlist
    )

    what_if = body.override is not None
    simpan = body.simpan and not what_if
    hasil["disimpan"] = False
    hasil["strategy_id"] = None
    hasil["catatan"] = []
    if what_if:
        hasil["catatan"].append("Mode what-if: hasil dihitung ulang dan tidak disimpan.")
    if simpan:
        hasil["strategy_id"] = str(
            strategi.simpan_strategi(db, sesi.id, body.jalur, pilihan_ids, hasil)
        )
        hasil["disimpan"] = True
    return hasil
