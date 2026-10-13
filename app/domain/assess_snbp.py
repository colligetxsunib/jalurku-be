"""Penilaian SNBP: INDIKATIF + tingkat keyakinan (PRD 8.2, model matriks 3x3). Fungsi murni.

- Tier siswa dari rapor semester 1-5 (rapor, tren, peringkat); `rapor` wajib.
- Pita keketatan dari rasio peminat/daya tampung SNBP; tanpa datanya -> belum_ada_acuan.
- Kategori = matriks[tier][pita] dari config.
- Keyakinan: `rendah` bila rekam jejak alumni kosong atau `tidak_tahu`, selain itu `sedang`.
  Data alumni TIDAK ikut menentukan sel matriks, hanya keyakinan dan catatan.
- Akreditasi sekolah tidak ikut menghitung tier (dipakai di gate kuota sekolah); hanya konteks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.config import JalurPenilaianConfig
from app.domain.assess_common import (
    BasisPita,
    Keketatan,
    Keyakinan,
    Penilaian,
    TierSiswa,
    nilai_dengan_matriks,
)

ALUMNI_DIKETAHUI = ("ya", "tidak")


def status_alumni(alumni_info: Mapping[str, str] | None, prodi_id: str, ptn_id: str) -> str:
    """'ya' | 'tidak' | 'tidak_tahu' | 'kosong'. Entri prodi didahulukan atas entri PTN."""
    info = alumni_info or {}
    for kunci in (prodi_id, ptn_id):
        if kunci in info and info[kunci] in ("ya", "tidak", "tidak_tahu"):
            return info[kunci]
    return "kosong"


def keyakinan_snbp(alumni: str, akreditasi: str | None):
    """Pembuat fungsi keyakinan untuk satu target."""

    def hitung(tier: TierSiswa) -> Keyakinan:
        catatan: list[str] = []
        if akreditasi:
            catatan.append(
                f"Akreditasi sekolah ({akreditasi}) menentukan kuota siswa eligible di syarat, "
                "bukan bagian dari tier siswa."
            )
        if alumni in ALUMNI_DIKETAHUI:
            catatan.append(
                "Ada alumni sekolahmu yang diterima di sini (konteks, tidak mengubah kategori)."
                if alumni == "ya"
                else "Belum ada alumni sekolahmu yang diterima di sini (konteks, tidak mengubah kategori)."
            )
            return Keyakinan("sedang", tuple(catatan))
        catatan.append(
            "Rekam jejak alumni sekolahmu tidak diketahui, jadi keyakinan rendah. "
            "Kuota sekolah dan riwayat alumni memengaruhi hasil SNBP."
        )
        return Keyakinan("rendah", tuple(catatan), ("alumni",))

    return hitung


def nilai_snbp(
    profil: Mapping[str, Any],
    *,
    prodi_id: str,
    ptn_id: str,
    keketatan: Keketatan | None,
    basis_pita: BasisPita,
    cfg: JalurPenilaianConfig,
    teks_catatan: Mapping[str, str],
    tahun_siklus: int,
) -> Penilaian:
    alumni = status_alumni(profil.get("alumni_info"), prodi_id, ptn_id)
    return nilai_dengan_matriks(
        jalur="SNBP",
        profil=profil,
        keketatan=keketatan,
        basis_pita=basis_pita,
        cfg=cfg,
        teks_catatan=teks_catatan,
        tahun_siklus=tahun_siklus,
        sumber_tier_rapor="rapor",
        peringatan_tier_rapor=None,
        pakai_skor_tryout=False,  # SNBP berbasis rapor, bukan skor tes
        keyakinan=keyakinan_snbp(alumni, profil.get("akreditasi_sekolah")),
        keterangan_sumber={"rapor": "dari rapor semester 1-5"},
    )
