"""Penilaian SNBT. Fungsi murni, tidak meng-import klien LLM.

Dua jalur, dipilih otomatis oleh data:
1. Ada baris `acuan_skor` untuk prodi: skor siswa dibandingkan dengan {rendah, tinggi} (PRD 8.2).
2. Selain itu (kondisi saat ini, tidak ada passing grade resmi): matriks 3x3 tier siswa x pita
   keketatan. Tier dari rapor hanya PROKSI, bukan skor UTBK, sehingga keyakinan `rendah`.
   Bila `skala_skor_tryout` diisi di config dan siswa punya skor, tier berpindah ke skor itu.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.config import JalurPenilaianConfig
from app.domain.assess_common import (
    PERINGATAN_PROKSI,
    BasisPita,
    Keketatan,
    Keyakinan,
    Penilaian,
    TierSiswa,
    nilai_dengan_matriks,
)
from app.domain.fields import pertanyaan_untuk
from app.domain.gate import DataKurang


@dataclass(frozen=True)
class AcuanSkor:
    rendah: float
    tinggi: float
    tahun: int


def _g(x: float) -> str:
    return f"{x:g}"


def nilai_dengan_acuan(skor: float | None, acuan: AcuanSkor, *, tahun_siklus: int) -> Penilaian:
    """safe: skor >= tinggi; match: rendah <= skor < tinggi; reach: skor < rendah (gap = rendah - skor)."""
    info = {"rendah": acuan.rendah, "tinggi": acuan.tinggi, "tahun": acuan.tahun}
    label = "acuan siklus sebelumnya" if acuan.tahun < tahun_siklus else None
    if skor is None:
        return Penilaian(
            kategori="data_kurang",
            metode="acuan_skor",
            indikatif=False,
            label=label,
            alasan="Skor tryout belum diisi, sehingga tidak bisa dibandingkan dengan acuan prodi.",
            acuan=info,
            data_kurang=(DataKurang("skor_tryout", pertanyaan_untuk("skor_tryout")),),
        )
    if skor >= acuan.tinggi:
        kategori, gap = "safe", None
        alasan = (
            f"Skor {_g(skor)} berada di atas atau sama dengan batas atas acuan {_g(acuan.tinggi)}."
        )
    elif skor >= acuan.rendah:
        kategori, gap = "match", None
        alasan = f"Skor {_g(skor)} berada di dalam rentang acuan {_g(acuan.rendah)} sampai {_g(acuan.tinggi)}."
    else:
        kategori, gap = "reach", acuan.rendah - skor
        alasan = f"Skor {_g(skor)} di bawah rentang acuan tahun lalu ({_g(acuan.rendah)} sampai {_g(acuan.tinggi)})."
    return Penilaian(
        kategori=kategori,
        metode="acuan_skor",
        indikatif=False,
        label=label,
        keyakinan="sedang",
        alasan=alasan,
        gap=gap,
        acuan=info,
        catatan=(
            ("Acuan berasal dari siklus sebelumnya. Cek ulang saat pendaftaran dibuka.",)
            if label
            else ()
        ),
    )


def _keyakinan(tier: TierSiswa) -> Keyakinan:
    if tier.sumber == "skor_tryout":
        return Keyakinan("sedang")
    return Keyakinan("rendah", (PERINGATAN_PROKSI,))


def nilai_snbt(
    profil: Mapping[str, Any],
    *,
    acuan: AcuanSkor | None,
    keketatan: Keketatan | None,
    basis_pita: BasisPita,
    cfg: JalurPenilaianConfig,
    teks_catatan: Mapping[str, str],
    tahun_siklus: int,
) -> Penilaian:
    if acuan is not None:
        return nilai_dengan_acuan(profil.get("skor_tryout"), acuan, tahun_siklus=tahun_siklus)

    return nilai_dengan_matriks(
        jalur="SNBT",
        profil=profil,
        keketatan=keketatan,
        basis_pita=basis_pita,
        cfg=cfg,
        teks_catatan=teks_catatan,
        tahun_siklus=tahun_siklus,
        sumber_tier_rapor="proksi_rapor",
        peringatan_tier_rapor=PERINGATAN_PROKSI,
        pakai_skor_tryout=True,
        keyakinan=_keyakinan,
        keterangan_sumber={
            "proksi_rapor": "proksi dari rapor, bukan skor UTBK",
            "skor_tryout": "dari skor tryout",
        },
    )
