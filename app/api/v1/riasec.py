"""Tes minat RIASEC. Template tetap, skoring deterministik, tanpa LLM. Bukan tes psikologi."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import batasi_ip, get_config, sesi_saat_ini
from app.core.config import AppConfig
from app.core.errors import AppError
from app.db.session import get_db
from app.domain import riasec as domain
from app.schemas.riasec import HasilOut, PertanyaanOut, RiasecSubmit
from app.services import profile as layanan_profil
from app.services import riasec as layanan
from app.services.sessions import SesiAktif

router = APIRouter(tags=["riasec"])


def _instrumen(request: Request) -> domain.Instrumen:
    return request.app.state.riasec


@router.get("/riasec/questions", response_model=PertanyaanOut, dependencies=[Depends(batasi_ip)])
def pertanyaan(request: Request, config: AppConfig = Depends(get_config)) -> dict:
    """Instrumen tes minat: skala, dimensi, dan butir. Publik (tanpa token)."""
    i = _instrumen(request)
    return {
        "versi_instrumen": i.versi_instrumen,
        "sumber": i.sumber,
        "instrumen_contoh": i.contoh,
        "skala": {"min": i.skala_min, "maks": i.skala_maks, "label": dict(i.skala_label)},
        "dimensi": list(i.dimensi),
        "item": [{"id": b.id, "teks": b.teks, "dimensi": b.dimensi} for b in i.item],
        "pernyataan": config.riasec.pernyataan,
        "min_terjawab": config.riasec.min_terjawab_per_dimensi,
    }


@router.post("/riasec/submit", response_model=HasilOut)
def kirim(
    body: RiasecSubmit,
    request: Request,
    sesi: SesiAktif = Depends(sesi_saat_ini),
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict:
    """Hitung skor minat dari jawaban (boleh parsial). `simpan=true` memetakannya ke `profil.minat`."""
    instr = _instrumen(request)
    galat = domain.validasi_jawaban(instr, body.jawaban)
    if galat:
        raise AppError(
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            status_code=422,
            detail={
                "field": [{"field": f, "pesan": p, "tipe": "value_error"} for f, p in galat[:50]]
            },
        )
    hasil = domain.hitung(instr, body.jawaban, config.riasec)

    tersimpan = False
    if body.simpan and hasil.skor_norm:
        # Pemetaan ke profil.minat: dimensi yang tidak dihitung dihapus (None), bukan dianggap 0.
        minat = {d: hasil.skor_norm.get(d) for d in instr.dimensi}
        ref = request.app.state.refdata.get(db)
        dasar = layanan_profil.baca_profil(db, sesi.id)
        gabungan = layanan_profil.profil_gabungan(db, dasar, {"minat": minat}, config, ref)
        layanan_profil.simpan_profil(db, sesi.id, gabungan)
        layanan.simpan_hasil(db, sesi.id, instr, hasil, hasil.skor_norm)
        tersimpan = True

    catatan = config.riasec.pernyataan
    if hasil.alasan:
        catatan += " Keyakinan rendah: " + "; ".join(hasil.alasan) + "."
    if body.simpan and not tersimpan:
        catatan += " Hasil tidak disimpan karena belum ada dimensi yang cukup terjawab."
    return {
        "versi_instrumen": instr.versi_instrumen,
        "instrumen_contoh": instr.contoh,
        "holland_code": hasil.holland_code,
        "dimensi_teratas": hasil.dimensi_teratas,
        "skor_norm": hasil.skor_norm,
        "terjawab": hasil.terjawab,
        "total_item": hasil.total_item,
        "terjawab_per_dimensi": hasil.terjawab_per_dimensi,
        "dimensi_tidak_dihitung": hasil.dimensi_tidak_dihitung,
        "keyakinan": hasil.keyakinan,
        "alasan_keyakinan": hasil.alasan,
        "tersimpan": tersimpan,
        "pernyataan": config.riasec.pernyataan,
        "catatan": catatan,
    }
