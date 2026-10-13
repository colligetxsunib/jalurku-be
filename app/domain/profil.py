"""Aturan profil siswa: penggabungan parsial dan validasi lintas-field. Fungsi murni.

Semantik PUT parsial (FR-P1, kriteria 7.2):
- field yang tidak dikirim tidak berubah;
- `null` eksplisit menghapus nilai field;
- field berbentuk dict digabung per kunci (nilai_rapor per semester lalu per mapel); nilai `null`
  pada sebuah kunci menghapus kunci itu.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

FIELD_SKALAR = (
    "tahun_lulus",
    "provinsi",
    "jenjang_sekolah",
    "akreditasi_sekolah",
    "skor_tryout",
    "peringkat_sekolah",
    "jumlah_siswa_angkatan",
    "punya_nilai_tka",
    "sekolah_punya_npsn",
    "sekolah_kurikulum_nasional",
    "pakai_erapor",
    "rapor_lengkap_di_pdss",
    "wni_punya_nik",
    "lulus_snbp_3_tahun_terakhir",
    "sudah_ikut_utbk_tahun_siklus",
    "paket_c_usia_per_1_juli",
)
FIELD_DICT_DANGKAL = ("minat", "alumni_info", "konfirmasi_syarat_prodi")
FIELD_DICT_BERSARANG = ("nilai_rapor",)
PROFIL_FIELDS: tuple[str, ...] = FIELD_SKALAR + FIELD_DICT_DANGKAL + FIELD_DICT_BERSARANG


@dataclass(frozen=True)
class AturanProfil:
    tahun_siklus: int
    tahun_lulus_mundur: int
    tahun_lulus_maju: int
    skor_tryout_min: float
    skor_tryout_maks: float
    paket_c_usia_min: int
    paket_c_usia_maks: int
    dimensi_minat: tuple[str, ...]


def profil_kosong() -> dict[str, Any]:
    return dict.fromkeys(PROFIL_FIELDS)


def gabung_profil(dasar: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Terapkan `patch` (hanya field yang dikirim) ke `dasar`. Tidak mengubah argumen."""
    hasil = {f: deepcopy(dasar.get(f)) for f in PROFIL_FIELDS}
    for nama, nilai in patch.items():
        if nama not in PROFIL_FIELDS:
            raise ValueError(f"field profil tidak dikenal: {nama}")
        if nilai is None:
            hasil[nama] = None
        elif nama in FIELD_DICT_DANGKAL:
            baru = dict(hasil[nama] or {})
            for kunci, v in nilai.items():
                if v is None:
                    baru.pop(kunci, None)
                else:
                    baru[kunci] = v
            hasil[nama] = baru or None
        elif nama in FIELD_DICT_BERSARANG:
            baru = deepcopy(hasil[nama] or {})
            for semester, mapel in nilai.items():
                if mapel is None:
                    baru.pop(semester, None)
                    continue
                sekarang = dict(baru.get(semester) or {})
                for nama_mapel, skor in mapel.items():
                    if skor is None:
                        sekarang.pop(nama_mapel, None)
                    else:
                        sekarang[nama_mapel] = skor
                if sekarang:
                    baru[semester] = sekarang
                else:
                    baru.pop(semester, None)
            hasil[nama] = baru or None
        else:
            hasil[nama] = nilai
    return hasil


def validasi_profil(profil: Mapping[str, Any], aturan: AturanProfil) -> list[tuple[str, str]]:
    """Validasi yang bergantung pada siklus/config/lintas-field. Mengembalikan [(field, pesan)]."""
    galat: list[tuple[str, str]] = []

    tahun = profil.get("tahun_lulus")
    if tahun is not None:
        bawah = aturan.tahun_siklus - aturan.tahun_lulus_mundur
        atas = aturan.tahun_siklus + aturan.tahun_lulus_maju
        if not bawah <= tahun <= atas:
            galat.append(("tahun_lulus", f"tahun lulus harus antara {bawah} dan {atas}"))

    peringkat, jumlah = profil.get("peringkat_sekolah"), profil.get("jumlah_siswa_angkatan")
    if peringkat is not None and jumlah is not None and peringkat > jumlah:
        pesan = f"peringkat ({peringkat}) tidak boleh melebihi jumlah siswa angkatan ({jumlah})"
        galat.append(("peringkat_sekolah", pesan))
        galat.append(("jumlah_siswa_angkatan", pesan))

    skor = profil.get("skor_tryout")
    if skor is not None and not aturan.skor_tryout_min <= skor <= aturan.skor_tryout_maks:
        galat.append(
            (
                "skor_tryout",
                f"skor tryout harus antara {aturan.skor_tryout_min:g} dan {aturan.skor_tryout_maks:g}",
            )
        )

    usia = profil.get("paket_c_usia_per_1_juli")
    if usia is not None and not aturan.paket_c_usia_min <= usia <= aturan.paket_c_usia_maks:
        galat.append(
            (
                "paket_c_usia_per_1_juli",
                f"usia harus antara {aturan.paket_c_usia_min} dan {aturan.paket_c_usia_maks}",
            )
        )

    asing = sorted(set(profil.get("minat") or {}) - set(aturan.dimensi_minat))
    if asing:
        galat.append(
            (
                "minat",
                f"dimensi minat tidak dikenal: {', '.join(asing)}. Pilihan: {', '.join(aturan.dimensi_minat)}",
            )
        )
    return galat


def rapor_ada(profil: Mapping[str, Any]) -> bool:
    """True bila ada setidaknya satu nilai rapor."""
    rapor = profil.get("nilai_rapor") or {}
    return any(isinstance(m, Mapping) and len(m) > 0 for m in rapor.values())
