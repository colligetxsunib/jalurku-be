"""Skoring tes minat RIASEC: fungsi murni dan deterministik, tanpa LLM dan tanpa I/O.

skor_norm dimensi = (rerata jawaban butir dimensi itu - skala.min) / (skala.maks - skala.min), 0..1.
Dimensi dengan butir terjawab di bawah ambang tidak dihitung (bukan dianggap nol). Holland code =
huruf tiga dimensi teratas. Cek kualitas hanya menurunkan keyakinan; hasil tidak pernah ditolak.
Ini gambaran minat awal, bukan tes psikologi dan bukan diagnosis.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.config import RiasecConfig

KEYAKINAN_SEDANG = "sedang"
KEYAKINAN_RENDAH = "rendah"

ALASAN_CONTOH = "instrumen contoh, bukan instrumen final"


@dataclass(frozen=True)
class Butir:
    id: str
    teks: str
    dimensi: str


@dataclass(frozen=True)
class Instrumen:
    versi_instrumen: str
    sumber: str
    skala_min: int
    skala_maks: int
    skala_label: Mapping[str, str]
    dimensi: tuple[str, ...]
    item: tuple[Butir, ...]
    contoh: bool = False  # True = berkas contoh sementara, bukan instrumen yang disusun tim


@dataclass(frozen=True)
class HasilRiasec:
    skor_norm: dict[str, float]  # hanya dimensi yang dihitung
    dimensi_teratas: list[str]
    holland_code: str | None
    terjawab: int
    total_item: int
    terjawab_per_dimensi: dict[str, int]
    total_per_dimensi: dict[str, int]
    dimensi_tidak_dihitung: list[str]
    keyakinan: str
    alasan: list[str] = field(default_factory=list)


def validasi_jawaban(instr: Instrumen, jawaban: Mapping[str, int]) -> list[tuple[str, str]]:
    """[(field, pesan)] untuk id butir yang tidak dikenal atau nilai di luar skala."""
    ada = {b.id for b in instr.item}
    galat: list[tuple[str, str]] = []
    for butir_id, nilai in jawaban.items():
        if butir_id not in ada:
            galat.append((f"jawaban.{butir_id}", "butir tidak dikenal"))
        elif not instr.skala_min <= nilai <= instr.skala_maks:
            galat.append(
                (f"jawaban.{butir_id}", f"nilai harus {instr.skala_min} sampai {instr.skala_maks}")
            )
    return galat


def hitung(instr: Instrumen, jawaban: Mapping[str, int], cfg: RiasecConfig) -> HasilRiasec:
    """Skor, Holland code, dan keyakinan dari jawaban (sudah divalidasi `validasi_jawaban`)."""
    rentang = instr.skala_maks - instr.skala_min
    total_dim = {d: 0 for d in instr.dimensi}
    nilai_dim: dict[str, list[int]] = {d: [] for d in instr.dimensi}
    for b in instr.item:
        total_dim[b.dimensi] += 1
        if b.id in jawaban:
            nilai_dim[b.dimensi].append(jawaban[b.id])
    terjawab_dim = {d: len(v) for d, v in nilai_dim.items()}

    skor: dict[str, float] = {}
    tidak_dihitung: list[str] = []
    for d in instr.dimensi:
        if terjawab_dim[d] >= cfg.min_terjawab_per_dimensi:
            rerata = sum(nilai_dim[d]) / terjawab_dim[d]
            skor[d] = round((rerata - instr.skala_min) / rentang, 4)
        else:
            tidak_dihitung.append(d)

    urutan = {d: i for i, d in enumerate(instr.dimensi)}
    teratas = sorted(skor, key=lambda d: (-skor[d], urutan[d]))[: cfg.jumlah_dimensi_kode]
    kode = "".join(cfg.kode_huruf[d] for d in teratas) or None

    nilai_semua = [v for vs in nilai_dim.values() for v in vs]
    terjawab = len(nilai_semua)
    alasan: list[str] = []
    if instr.contoh:
        alasan.append(ALASAN_CONTOH)
    if not skor:
        alasan.append("tidak ada dimensi dengan jawaban cukup untuk dihitung")
    sedikit = [
        d
        for d in instr.dimensi
        if total_dim[d] and terjawab_dim[d] / total_dim[d] < cfg.min_rasio_terjawab_per_dimensi
    ]
    if sedikit and skor:
        alasan.append("terlalu sedikit butir terjawab pada dimensi: " + ", ".join(sedikit))
    if terjawab >= cfg.min_terjawab_untuk_seragam:
        paling_sering = Counter(nilai_semua).most_common(1)[0][1]
        if paling_sering / terjawab >= cfg.maks_rasio_jawaban_seragam:
            alasan.append(f"jawaban hampir seragam ({paling_sering} dari {terjawab} butir sama)")
    if len(skor) >= 2:
        selisih = max(skor.values()) - min(skor.values())
        if selisih < cfg.min_selisih_skor:
            alasan.append(
                f"profil minat datar (selisih skor tertinggi dan terendah {selisih:.2f}), "
                "minat belum membedakan antar bidang"
            )

    return HasilRiasec(
        skor_norm=skor,
        dimensi_teratas=teratas,
        holland_code=kode,
        terjawab=terjawab,
        total_item=len(instr.item),
        terjawab_per_dimensi=terjawab_dim,
        total_per_dimensi=total_dim,
        dimensi_tidak_dihitung=tidak_dihitung,
        keyakinan=KEYAKINAN_RENDAH if alasan else KEYAKINAN_SEDANG,
        alasan=alasan,
    )
