"""Orkestrasi strategi pilihan (FR-S1 sampai S4): analisis tiap pilihan, evaluasi komposisi, swap, simpan."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.domain.strategy import (
    AturanStrategi,
    Pilihan,
    evaluasi,
    hitung_komposisi,
    tambah_saran_swap,
)
from app.services.analisis import analisis_satu, muat_target
from app.services.refdata import RefData


def aturan_dari_data(ref: RefData, config: AppConfig, jalur: str) -> AturanStrategi:
    """Batas pilihan dan komposisi dari ketentuan resmi (data), heuristik dari config."""
    k, tahun = ref.ketentuan, ref.tahun_siklus
    komposisi: dict[int, Any] | None = None
    if k.punya("komposisi_pilihan_1_2", jalur, tahun) or k.punya(
        "komposisi_pilihan_3", jalur, tahun
    ):
        komposisi = {}
        if k.punya("komposisi_pilihan_1_2", jalur, tahun):
            komposisi[1] = komposisi[2] = "bebas"
        for n in (3, 4):
            if k.punya(f"komposisi_pilihan_{n}", jalur, tahun):
                komposisi[n] = k.struktur(f"komposisi_pilihan_{n}", jalur, tahun)
    s = config.strategi
    return AturanStrategi(
        jalur=jalur,
        max_pilihan=int(k.angka("max_pilihan_prodi", jalur, tahun)),
        komposisi=komposisi,
        aturan_provinsi=k.punya("aturan_provinsi_pilihan", jalur, tahun),
        blokir_lintas_jalur=k.punya("blokir_lintas_jalur", jalur, tahun),
        min_pilihan_untuk_evaluasi=s.min_pilihan_untuk_evaluasi,
        min_safe=s.min_safe,
        maks_rasio_reach=s.maks_rasio_reach,
        peringatan_satu_ptn=s.peringatan_satu_ptn,
        peringatan_satu_jalur=s.peringatan_satu_jalur,
        maks_saran_swap=s.maks_saran_swap,
    )


def ke_pilihan(hasil: Mapping[str, Any]) -> Pilihan:
    p = hasil["prodi"]
    penilaian = hasil["penilaian"] or {}
    return Pilihan(
        prodi_id=hasil["prodi_id"],
        nama=p["nama"],
        ptn_id=p["ptn_id"],
        ptn_nama=p["ptn_nama"],
        provinsi_ptn=p["ptn_provinsi"],
        program=p["program"],
        jenjang=p["jenjang"],
        status_gate=hasil["gate"]["status"],
        kategori=penilaian.get("kategori"),
    )


def ada_strategi_jalur_lain(db: Session, session_id: uuid.UUID, jalur: str) -> bool:
    return (
        db.execute(
            select(m.Strategi.id)
            .where(m.Strategi.session_id == session_id, m.Strategi.jalur != jalur)
            .limit(1)
        ).first()
        is not None
    )


def evaluasi_strategi(
    db: Session,
    ref: RefData,
    config: AppConfig,
    session_id: uuid.UUID,
    profil: Mapping[str, Any],
    jalur: str,
    pilihan_ids: Sequence[str],
    shortlist_ids: Sequence[str],
) -> dict[str, Any]:
    dimuat = muat_target(db, [*pilihan_ids, *shortlist_ids])
    hasil = [analisis_satu(db, ref, config, profil, dimuat[pid], jalur) for pid in pilihan_ids]
    pilihan = [ke_pilihan(h) for h in hasil]
    kandidat = [
        ke_pilihan(analisis_satu(db, ref, config, profil, dimuat[pid], jalur))
        for pid in shortlist_ids
        if pid not in pilihan_ids
    ]

    aturan = aturan_dari_data(ref, config, jalur)
    provinsi = profil.get("provinsi")
    lain = ada_strategi_jalur_lain(db, session_id, jalur)
    temuan = evaluasi(pilihan, aturan, provinsi_sekolah=provinsi, ada_strategi_jalur_lain=lain)
    temuan = tambah_saran_swap(
        temuan, pilihan, kandidat, aturan, provinsi_sekolah=provinsi, ada_strategi_jalur_lain=lain
    )
    return {
        "jalur": jalur,
        "batas_pilihan": aturan.max_pilihan,
        "hasil": hasil,
        "komposisi": hitung_komposisi(pilihan),
        "temuan": [t.ke_dict() for t in temuan],
    }


def simpan_strategi(
    db: Session,
    session_id: uuid.UUID,
    jalur: str,
    pilihan_ids: Sequence[str],
    evaluasi_hasil: Mapping[str, Any],
) -> uuid.UUID:
    baris = m.Strategi(
        id=uuid.uuid4(),
        session_id=session_id,
        jalur=jalur,
        pilihan=[{"prodi_id": pid} for pid in pilihan_ids],
        hasil_evaluasi={
            "komposisi": evaluasi_hasil["komposisi"],
            "temuan": evaluasi_hasil["temuan"],
        },
    )
    db.add(baris)
    db.commit()
    return baris.id
