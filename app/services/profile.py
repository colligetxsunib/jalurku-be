"""Layanan profil: baca/simpan, gabung patch + validasi, dan penghitungan `data_kurang` per jalur."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.errors import AppError
from app.db import models as m
from app.domain.fields import PREFIKS_KONFIRMASI_PRODI, pertanyaan_untuk
from app.domain.gate import DataKurang, evaluasi_gate
from app.domain.profil import (
    PROFIL_FIELDS,
    AturanProfil,
    gabung_profil,
    profil_kosong,
    rapor_ada,
    validasi_profil,
)
from app.services.refdata import RefData

JALUR = ("SNBP", "SNBT")


def aturan_profil(config: AppConfig, ref: RefData) -> AturanProfil:
    p = config.profil
    return AturanProfil(
        tahun_siklus=ref.tahun_siklus,
        tahun_lulus_mundur=p.tahun_lulus_mundur,
        tahun_lulus_maju=p.tahun_lulus_maju,
        skor_tryout_min=p.skor_tryout_min,
        skor_tryout_maks=p.skor_tryout_maks,
        paket_c_usia_min=p.paket_c_usia_min,
        paket_c_usia_maks=p.paket_c_usia_maks,
        dimensi_minat=tuple(config.minat.dimensi),
    )


def baca_profil(db: Session, session_id: uuid.UUID) -> dict[str, Any]:
    """Profil tersimpan sebagai dict lengkap (field belum diisi bernilai None)."""
    baris = db.get(m.Profil, session_id)
    if baris is None:
        return profil_kosong()
    return {f: getattr(baris, f) for f in PROFIL_FIELDS}


def simpan_profil(db: Session, session_id: uuid.UUID, profil: Mapping[str, Any]) -> None:
    baris = db.get(m.Profil, session_id)
    if baris is None:
        baris = m.Profil(session_id=session_id)
        db.add(baris)
    for f in PROFIL_FIELDS:
        setattr(baris, f, profil.get(f))
    db.commit()


def _error_validasi(galat: list[tuple[str, str]]) -> AppError:
    return AppError(
        "validasi_gagal",
        "Data yang dikirim tidak valid",
        status_code=422,
        detail={"field": [{"field": f, "pesan": p, "tipe": "value_error"} for f, p in galat]},
    )


def profil_gabungan(
    db: Session,
    dasar: Mapping[str, Any],
    patch: Mapping[str, Any],
    config: AppConfig,
    ref: RefData,
) -> dict[str, Any]:
    """Gabungkan patch ke profil dasar dan validasi. Tidak menulis ke DB.

    Dipakai PUT /profile (lalu disimpan) dan `override` what-if (tidak pernah disimpan).
    Hanya error pada field yang ada di patch yang dilaporkan, supaya profil lama yang kebetulan
    tidak lagi sesuai config tidak memblokir pembaruan field lain.
    """
    gabungan = gabung_profil(dasar, patch)
    galat = [(f, p) for f, p in validasi_profil(gabungan, aturan_profil(config, ref)) if f in patch]

    id_prodi = [k for k, v in (patch.get("konfirmasi_syarat_prodi") or {}).items() if v is not None]
    if id_prodi:
        ada = set(db.execute(select(m.Prodi.id).where(m.Prodi.id.in_(id_prodi))).scalars())
        for pid in sorted(set(id_prodi) - ada):
            galat.append(("konfirmasi_syarat_prodi", f"prodi_id '{pid}' tidak ada di katalog"))
    if galat:
        raise _error_validasi(galat)
    return gabungan


def hitung_data_kurang(ref: RefData, profil: Mapping[str, Any]) -> dict[str, list[DataKurang]]:
    """Data yang masih dibutuhkan per jalur, pada tingkat profil (tanpa target prodi tertentu).

    Jalur yang pasti gugur (ada syarat gagal) tidak meminta data tambahan.
    """
    hasil: dict[str, list[DataKurang]] = {}
    for jalur in JALUR:
        rules = ref.rules.get(jalur)
        if rules is None:
            hasil[jalur] = []
            continue
        gate = evaluasi_gate(rules, profil, ref.ketentuan)
        if gate.status == "tidak_memenuhi_syarat":
            hasil[jalur] = []
            continue
        kurang = [d for d in gate.data_kurang if not d.field.startswith(PREFIKS_KONFIRMASI_PRODI)]
        if not rapor_ada(profil):  # dibutuhkan penilaian reach/match/safe
            kurang.append(DataKurang("nilai_rapor", pertanyaan_untuk("nilai_rapor")))
        hasil[jalur] = kurang
    return hasil


def ke_respons(
    profil: Mapping[str, Any], data_kurang: Mapping[str, list[DataKurang]]
) -> dict[str, Any]:
    pertanyaan: dict[str, str] = {}
    for daftar in data_kurang.values():
        for d in daftar:
            pertanyaan.setdefault(d.field, d.pertanyaan)
    return {
        "profil": {f: profil.get(f) for f in PROFIL_FIELDS},
        "data_kurang": {j: [d.field for d in daftar] for j, daftar in data_kurang.items()},
        "pertanyaan": pertanyaan,
    }
