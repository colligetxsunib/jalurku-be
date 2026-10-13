"""Ringkasan strategi (FR-R1, FR-R2): dokumen akhir dari strategi tersimpan.

Semua angka dan status dihitung ulang oleh mesin aturan dari pilihan tersimpan + profil saat ini.
Tidak ada tautan/token publik: ringkasan hanya dikembalikan lewat POST /summary dengan token sesi.

LLM hanya boleh menyusun narasi dari fakta mesin aturan (opsional). Narasi LLM dipakai hanya bila
lolos `narasi_aman`; selain itu (LLM mati, kuota habis, ditolak pagar) narasi template yang dipakai
dan seluruh ringkasan tetap lengkap.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.errors import AppError
from app.db import models as m
from app.domain.ringkasan import (
    KALIMAT_PENUTUP,
    catatan_ringkasan,
    fakta_narasi,
    fokus_satu_pilihan,
    gabung_fokus,
    narasi_template,
)
from app.llm.guard import narasi_aman
from app.llm.prompts import SISTEM_NARASI, prompt_narasi
from app.llm.service import LLMService
from app.services.analisis import muat_target
from app.services.katalog import status_verifikasi
from app.services.refdata import RefData
from app.services.strategi import evaluasi_strategi

log = logging.getLogger("jalurku.ringkasan")

URUTAN_JALUR = {"SNBP": 0, "SNBT": 1}
MAKS_TOKEN_NARASI = 400


def pilih_strategi(
    db: Session, session_id: uuid.UUID, strategy_id: uuid.UUID | None
) -> list[m.Strategi]:
    if strategy_id is not None:
        baris = db.execute(
            select(m.Strategi).where(
                m.Strategi.id == strategy_id, m.Strategi.session_id == session_id
            )
        ).scalar_one_or_none()
        if baris is None:  # id milik sesi lain diperlakukan sama dengan tidak ada
            raise AppError("strategi_tidak_ditemukan", "Strategi tidak ditemukan", status_code=404)
        return [baris]

    semua = db.execute(
        select(m.Strategi)
        .where(m.Strategi.session_id == session_id)
        .order_by(m.Strategi.created_at.desc(), m.Strategi.id)
    ).scalars()
    terbaru: dict[str, m.Strategi] = {}
    for s in semua:
        terbaru.setdefault(s.jalur, s)
    if not terbaru:
        raise AppError(
            "strategi_belum_disimpan",
            "Belum ada strategi tersimpan. Simpan dulu lewat POST /strategy dengan simpan=true.",
            status_code=404,
        )
    return sorted(terbaru.values(), key=lambda s: URUTAN_JALUR.get(s.jalur, 9))


def _dokumen(ref: RefData, jalur: str) -> list[dict[str, Any]]:
    rules = ref.rules.get(jalur)
    if rules is None:
        return []
    hasil = []
    for d in rules.dokumen_wajib:
        tanggal = d.get("terakhir_diverifikasi")
        hasil.append(
            {
                "jalur": jalur,
                "nama": d["nama"],
                "sumber_url": d.get("sumber_url"),
                "terakhir_diverifikasi": tanggal,
                "status_verifikasi": status_verifikasi(
                    datetime.fromisoformat(tanggal).date() if tanggal else None
                ),
            }
        )
    return hasil


def susun_ringkasan(
    db: Session,
    ref: RefData,
    config: AppConfig,
    session_id: uuid.UUID,
    profil: Mapping[str, Any],
    rows: list[m.Strategi],
    *,
    llm: LLMService | None = None,
    izin_llm: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    pilihan_akhir: list[dict[str, Any]] = []
    gap: list[dict[str, Any]] = []
    fokus_mentah: list[dict[str, Any]] = []
    dokumen: list[dict[str, Any]] = []
    alasan: list[str] = []
    strategi: list[dict[str, Any]] = []
    bagian_narasi: list[dict[str, Any]] = []
    semua_hasil: list[Mapping[str, Any]] = []

    for row in rows:
        jalur = row.jalur
        ids = [p["prodi_id"] for p in row.pilihan]
        ev = evaluasi_strategi(db, ref, config, session_id, profil, jalur, ids, [])
        prodi_dimuat = muat_target(db, ids)
        k = ev["komposisi"]
        n_pelanggaran = sum(t["tingkat"] == "pelanggaran" for t in ev["temuan"])
        n_peringatan = sum(t["tingkat"] == "peringatan" for t in ev["temuan"])

        for urutan, h in enumerate(ev["hasil"], start=1):
            semua_hasil.append(h)
            p = h["penilaian"]
            pilihan_akhir.append(
                {
                    "jalur": jalur,
                    "urutan": urutan,
                    "prodi_id": h["prodi_id"],
                    "prodi": h["prodi"]["nama"],
                    "ptn": h["prodi"]["ptn_nama"],
                    "jenjang": h["prodi"]["jenjang"],
                    "program": h["prodi"]["program"],
                    "status_gate": h["gate"]["status"],
                    "kategori": p["kategori"] if p else None,
                    "keyakinan": p["keyakinan"] if p else None,
                    "indikatif": p["indikatif"] if p else None,
                    "alasan": p["alasan"] if p else _alasan_tanpa_penilaian(h),
                    "gap": p["gap"] if p else None,
                    "sumber": h["sumber"],
                    "terakhir_diverifikasi": h["terakhir_diverifikasi"],
                    "status_verifikasi": h["status_verifikasi"],
                }
            )
            if p and p.get("gap"):
                gap.append(
                    {
                        "jalur": jalur,
                        "prodi_id": h["prodi_id"],
                        "gap": p["gap"],
                        "satuan": "poin skor tryout",
                    }
                )
            fokus_mentah.extend(
                fokus_satu_pilihan(
                    jalur, h, profil, prodi_dimuat[h["prodi_id"]].prodi.mapel_penentu
                )
            )

        dokumen.extend(_dokumen(ref, jalur))
        alasan.append(
            f"{jalur}: {k['jumlah']} pilihan ({k['reach']} reach, {k['match']} match, {k['safe']} safe, "
            f"{k['tidak_dinilai']} belum dapat dinilai). Temuan: {n_pelanggaran} pelanggaran aturan, "
            f"{n_peringatan} peringatan."
        )
        strategi.append(
            {
                "jalur": jalur,
                "strategy_id": str(row.id),
                "disimpan_pada": row.created_at.isoformat(),
                "batas_pilihan": ev["batas_pilihan"],
                "komposisi": k,
                "temuan": ev["temuan"],
            }
        )
        bagian_narasi.append(
            {
                "jalur": jalur,
                "pelanggaran": n_pelanggaran,
                "peringatan": n_peringatan,
                "batas_pilihan": ev["batas_pilihan"],
                "komposisi": k,
                "pilihan": [
                    {
                        "nama": x["prodi"],
                        "ptn": x["ptn"],
                        "kategori": x["kategori"],
                        "status": x["status_gate"],
                        "keyakinan": x["keyakinan"],
                    }
                    for x in pilihan_akhir
                    if x["jalur"] == jalur
                ],
            }
        )

    narasi, narasi_fallback = _narasi(
        db,
        llm,
        izin_llm,
        fakta_narasi(bagian_narasi, ref.tahun_siklus),
        narasi_template(bagian_narasi),
    )
    return {
        "dihasilkan_pada": datetime.now(UTC).isoformat(),
        "pilihan_akhir": pilihan_akhir,
        "alasan": alasan,
        "gap": gap,
        "fokus_persiapan": gabung_fokus(fokus_mentah),
        "dokumen_syarat": dokumen,
        "catatan": catatan_ringkasan(semua_hasil, len(rows)),
        "strategi": strategi,
        "narasi": narasi,
        "narasi_fallback": narasi_fallback,  # True = teks template, False = disusun LLM dan lolos pagar
    }


def _narasi(
    db: Session,
    llm: LLMService | None,
    izin_llm: Callable[[], bool] | None,
    fakta: Mapping[str, Any],
    template: str,
) -> tuple[str, bool]:
    """(narasi, fallback). Tidak pernah melempar: kegagalan LLM berarti narasi template."""
    if llm is None or not llm.dikonfigurasi:
        return template, True
    hasil = llm.generate(
        db,
        namespace="narasi",
        system=SISTEM_NARASI,
        prompt=prompt_narasi(fakta),
        kunci_cache={"fakta": fakta},
        max_output_tokens=MAKS_TOKEN_NARASI,
        izin=izin_llm,
    )
    if hasil.teks is None:
        return template, True
    aman, alasan = narasi_aman(hasil.teks, fakta)
    if not aman:
        log.warning("narasi LLM ditolak pagar keluaran: %s", alasan)
        return template, True
    # Kalimat penutup tetap dari kode: label indikatif tidak bergantung pada LLM.
    return f"{hasil.teks.strip()} {KALIMAT_PENUTUP}", False


def _alasan_tanpa_penilaian(h: Mapping[str, Any]) -> str:
    if h["gate"]["status"] == "tidak_memenuhi_syarat":
        gagal = [
            s["alasan"] for s in h["gate"]["syarat"] if s["status"] == "gagal" and s.get("alasan")
        ]
        return "Tidak memenuhi syarat: " + "; ".join(gagal)
    return "Data belum lengkap untuk menilai pilihan ini."
