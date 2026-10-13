"""Skema profil siswa. Sengaja TANPA field identitas (nama, kontak, NIK, NISN): FR-P4.

`ProfilePatch` dipakai untuk PUT /profile dan sebagai `override` terstruktur di /analyze, /strategy,
dan /query (skema validasi yang sama). `extra="forbid"` menolak field tak dikenal dengan 422.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.domain.provinsi import normalisasi_provinsi

Semester = Annotated[str, StringConstraints(pattern=r"^semester_[1-6]$")]
Mapel = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
Nilai = Annotated[float, Field(ge=0, le=100)]
Skala01 = Annotated[float, Field(ge=0, le=1)]
KunciBebas = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class ProfilePatch(BaseModel):
    """Semua field opsional. Yang tidak dikirim tidak berubah; `null` menghapus nilainya."""

    model_config = ConfigDict(extra="forbid")

    tahun_lulus: int | None = Field(default=None, ge=1900, le=2200)
    provinsi: str | None = None  # provinsi sekolah asal, daftar baku
    jenjang_sekolah: Literal["SMA", "SMK", "MA", "Paket C"] | None = None
    akreditasi_sekolah: Literal["A", "B", "C", "tidak_terakreditasi"] | None = None
    nilai_rapor: dict[Semester, dict[Mapel, Nilai | None] | None] | None = None
    minat: dict[KunciBebas, Skala01 | None] | None = None
    skor_tryout: float | None = None
    peringkat_sekolah: int | None = Field(default=None, ge=1)
    jumlah_siswa_angkatan: int | None = Field(default=None, ge=1)
    alumni_info: dict[KunciBebas, Literal["ya", "tidak", "tidak_tahu"] | None] | None = None
    punya_nilai_tka: bool | None = None
    sekolah_punya_npsn: bool | None = None
    sekolah_kurikulum_nasional: bool | None = None
    pakai_erapor: bool | None = None
    rapor_lengkap_di_pdss: bool | None = None
    wni_punya_nik: bool | None = None  # boolean saja; NIK sendiri tidak pernah dikumpulkan
    lulus_snbp_3_tahun_terakhir: bool | None = None
    sudah_ikut_utbk_tahun_siklus: bool | None = None
    paket_c_usia_per_1_juli: int | None = Field(default=None, ge=0, le=150)
    konfirmasi_syarat_prodi: dict[KunciBebas, bool | None] | None = None

    @field_validator("provinsi")
    @classmethod
    def _provinsi_baku(cls, v: str | None) -> str | None:
        if v is None:
            return None
        baku = normalisasi_provinsi(v)
        if baku is None:
            raise ValueError("bukan provinsi baku (gunakan salah satu dari 38 provinsi)")
        return baku


class ProfilResponse(BaseModel):
    profil: dict[str, Any]
    data_kurang: dict[str, list[str]]
    pertanyaan: dict[str, str]
