"""Layanan tes minat RIASEC (PRD 8.3, FR-E2): sajikan item, skor jawaban, simpan ke profil.

Jembatan antara router, config (bank item + skala), domain murni (skoring), dan profil siswa.
Hasil tes menulis vektor `minat` di `profiles.minat` sehingga langsung dipakai `/explore`.
Tidak memanggil LLM: penjelasan hasil (opsional) dibangun di lapisan terpisah.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.errors import AppError
from app.domain import riasec as dom
from app.services import profile as layanan_profil
from app.services.refdata import RefData


def _instrumen(config: AppConfig) -> tuple[list[dom.ItemRiasec], dom.SkalaLikert]:
    item = [dom.ItemRiasec(id=i.id, dimensi=i.dimensi, teks=i.teks) for i in config.riasec.item]
    skala = dom.SkalaLikert(min=config.riasec.skala.min, maks=config.riasec.skala.maks)
    return item, skala


def pertanyaan(config: AppConfig) -> dict[str, Any]:
    """Instrumen untuk ditampilkan frontend (FR-E2). Tanpa kunci skoring, hanya item + skala."""
    r = config.riasec
    return {
        "versi_instrumen": r.versi_instrumen,
        "sumber": r.sumber,
        "skala": {"min": r.skala.min, "maks": r.skala.maks, "label": dict(r.skala.label)},
        "min_terjawab": r.min_terjawab,
        "dimensi": list(config.minat.dimensi),
        "item": [{"id": i.id, "dimensi": i.dimensi, "teks": i.teks} for i in r.item],
    }


def _error_validasi(galat: list[tuple[str, str]]) -> AppError:
    return AppError(
        "validasi_gagal",
        "Data yang dikirim tidak valid",
        status_code=422,
        detail={"field": [{"field": f, "pesan": p, "tipe": "value_error"} for f, p in galat]},
    )


def nilai(
    db: Session,
    session_id: uuid.UUID,
    jawaban: Mapping[str, int],
    config: AppConfig,
    ref: RefData,
    *,
    simpan: bool,
) -> dict[str, Any]:
    """Validasi jawaban, hitung vektor minat deterministik, dan (opsional) simpan ke profil."""
    if not config.riasec.aktif:
        raise AppError("fitur_nonaktif", "Tes minat sedang tidak tersedia", status_code=404)

    item, skala = _instrumen(config)

    galat: list[tuple[str, str]] = []
    for iid in dom.id_tak_dikenal(jawaban, item):
        galat.append(("jawaban", f"id item tidak dikenal: '{iid}'"))
    for iid in dom.jawaban_di_luar_skala(jawaban, skala):
        galat.append(("jawaban", f"nilai '{iid}' di luar skala {skala.min}..{skala.maks}"))
    if galat:
        raise _error_validasi(galat)

    hasil = dom.hitung(jawaban, item, skala, config.minat.dimensi)

    if config.riasec.min_terjawab and hasil.terjawab < config.riasec.min_terjawab:
        raise _error_validasi(
            [("jawaban", f"jawab minimal {config.riasec.min_terjawab} item (baru {hasil.terjawab})")]
        )

    tersimpan = False
    if simpan:
        dasar = layanan_profil.baca_profil(db, session_id)
        gabungan = layanan_profil.profil_gabungan(
            db, dasar, {"minat": dict(hasil.skor_norm)}, config, ref
        )
        layanan_profil.simpan_profil(db, session_id, gabungan)
        tersimpan = True

    catatan = (
        "Hasil tes minat bersifat indikatif, bukan vonis. Minat bisa berkembang; "
        "pertimbangkan bersama nilai dan kelayakan jalur."
    )
    return {
        "versi_instrumen": config.riasec.versi_instrumen,
        "skor_norm": hasil.skor_norm,
        "skor_mentah": hasil.skor_mentah,
        "holland_code": hasil.holland_code,
        "dimensi_teratas": hasil.dimensi_teratas,
        "jumlah_item": hasil.jumlah_item,
        "terjawab": hasil.terjawab,
        "total_item": hasil.total_item,
        "tersimpan": tersimpan,
        "catatan": catatan,
    }
