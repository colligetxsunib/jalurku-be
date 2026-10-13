"""Registry field gate: dari mana nilai berasal, dan pertanyaan `data_kurang` untuk siswa.

Setiap field yang dipakai rule WAJIB terdaftar di sini. Ingest menolak rule dengan field tak dikenal.
`kurang` pada hasil resolusi berisi nama field PROFIL yang perlu diisi siswa (bukan nama turunan).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

JENJANG_SEKOLAH = ("SMA", "SMK", "MA", "Paket C")
JENJANG_REGULER = ("SMA", "SMK", "MA")
AKREDITASI = ("A", "B", "C", "tidak_terakreditasi")
PREFIKS_KONFIRMASI_PRODI = "konfirmasi_syarat_prodi."


class FaktaTidakValid(ValueError):
    """Fakta profil bertentangan (mis. peringkat > jumlah siswa). Seharusnya ditolak validasi profil."""


@dataclass(frozen=True)
class Target:
    prodi_id: str
    nama: str | None = None


@dataclass(frozen=True)
class Resolved:
    nilai: Any = None
    kurang: tuple[str, ...] = ()
    tidak_berlaku: bool = False


Resolver = Callable[[Mapping[str, Any], "Target | None"], Resolved]


@dataclass(frozen=True)
class FieldDef:
    nama: str
    tipe: Literal["bool", "int", "float", "str"]
    sumber: Literal["profil", "turunan", "target"]
    resolver: Resolver


PERTANYAAN: dict[str, str] = {
    "tahun_lulus": "Tahun berapa kamu lulus (atau akan lulus) dari sekolah?",
    "provinsi": "Di provinsi mana sekolahmu berada?",
    "jenjang_sekolah": "Kamu bersekolah di jenjang apa (SMA, SMK, MA, atau Paket C)?",
    "akreditasi_sekolah": "Apa akreditasi sekolahmu (A, B, C, atau belum terakreditasi)?",
    "sekolah_punya_npsn": "Apakah sekolahmu punya Nomor Pokok Sekolah Nasional (NPSN)?",
    "sekolah_kurikulum_nasional": "Apakah sekolahmu memakai kurikulum nasional?",
    "peringkat_sekolah": "Kamu peringkat berapa di angkatanmu (satu sekolah)?",
    "jumlah_siswa_angkatan": "Berapa jumlah siswa di angkatanmu?",
    "pakai_erapor": "Apakah sekolahmu memakai e-Rapor untuk mengisi PDSS?",
    "punya_nilai_tka": "Apakah kamu sudah punya nilai TKA (Tes Kemampuan Akademik) Kemdikdasmen?",
    "rapor_lengkap_di_pdss": "Apakah nilai rapormu sudah terisi lengkap dan benar di PDSS oleh sekolah?",
    "wni_punya_nik": "Apakah kamu WNI yang memiliki NIK?",
    "lulus_snbp_3_tahun_terakhir": "Apakah kamu pernah dinyatakan lulus SNBP pada tahun ini atau dua tahun sebelumnya?",
    "sudah_ikut_utbk_tahun_siklus": "Apakah kamu sudah mengikuti UTBK pada tahun pendaftaran ini?",
    "paket_c_usia_per_1_juli": "Berapa usiamu per 1 Juli tahun pendaftaran? (khusus peserta Paket C)",
    "skor_tryout": "Berapa estimasi skor tryout UTBK kamu?",
    "nilai_rapor": "Berapa nilai rapor semester 1 sampai 5 untuk tiap mata pelajaran?",
    "minat": "Seberapa besar minatmu pada tiap bidang?",
}


def pertanyaan_untuk(field: str, target: Target | None = None) -> str:
    if field.startswith(PREFIKS_KONFIRMASI_PRODI):
        nama = target.nama if target and target.nama else "yang dituju"
        return (
            f"Apakah kamu memenuhi persyaratan khusus program studi {nama} "
            "(mis. portofolio untuk prodi seni atau olahraga)?"
        )
    return PERTANYAAN.get(field, f"Mohon lengkapi data: {field}")


def _langsung(nama: str) -> Resolver:
    def resolver(profil: Mapping[str, Any], target: Target | None) -> Resolved:
        v = profil.get(nama)
        return Resolved(nilai=v) if v is not None else Resolved(kurang=(nama,))

    return resolver


def _persentil_peringkat(profil: Mapping[str, Any], target: Target | None) -> Resolved:
    kurang = tuple(
        f for f in ("peringkat_sekolah", "jumlah_siswa_angkatan") if profil.get(f) is None
    )
    if kurang:
        return Resolved(kurang=kurang)
    peringkat, jumlah = profil["peringkat_sekolah"], profil["jumlah_siswa_angkatan"]
    if jumlah < 1 or peringkat < 1 or peringkat > jumlah:
        raise FaktaTidakValid("peringkat_sekolah harus antara 1 dan jumlah_siswa_angkatan")
    # Kali 100 dulu baru bagi: hasil eksak bila habis dibagi, sehingga batas inklusif aman.
    return Resolved(nilai=peringkat * 100 / jumlah)


def _usia_paket_c(profil: Mapping[str, Any], target: Target | None) -> Resolved:
    jenjang = profil.get("jenjang_sekolah")
    if jenjang is None:
        return Resolved(kurang=("jenjang_sekolah",))
    if jenjang in JENJANG_REGULER:
        return Resolved(tidak_berlaku=True)  # bukan Paket C: syarat dilewati
    usia = profil.get("paket_c_usia_per_1_juli")
    return (
        Resolved(nilai=usia) if usia is not None else Resolved(kurang=("paket_c_usia_per_1_juli",))
    )


def _konfirmasi_prodi(profil: Mapping[str, Any], target: Target | None) -> Resolved:
    assert target is not None
    nilai = (profil.get("konfirmasi_syarat_prodi") or {}).get(target.prodi_id)
    if nilai is None:
        return Resolved(kurang=(PREFIKS_KONFIRMASI_PRODI + target.prodi_id,))
    return Resolved(nilai=nilai)


def _daftar() -> dict[str, FieldDef]:
    langsung = [
        ("tahun_lulus", "int"),
        ("jenjang_sekolah", "str"),
        ("akreditasi_sekolah", "str"),
        ("sekolah_punya_npsn", "bool"),
        ("sekolah_kurikulum_nasional", "bool"),
        ("pakai_erapor", "bool"),
        ("punya_nilai_tka", "bool"),
        ("rapor_lengkap_di_pdss", "bool"),
        ("wni_punya_nik", "bool"),
        ("lulus_snbp_3_tahun_terakhir", "bool"),
        ("sudah_ikut_utbk_tahun_siklus", "bool"),
    ]
    reg = {n: FieldDef(n, t, "profil", _langsung(n)) for n, t in langsung}
    reg["persentil_peringkat_sekolah"] = FieldDef(
        "persentil_peringkat_sekolah", "float", "turunan", _persentil_peringkat
    )
    reg["paket_c_usia_per_1_juli"] = FieldDef(
        "paket_c_usia_per_1_juli", "int", "turunan", _usia_paket_c
    )
    reg["memenuhi_syarat_prodi"] = FieldDef(
        "memenuhi_syarat_prodi", "bool", "target", _konfirmasi_prodi
    )
    return reg


FIELD_REGISTRY: dict[str, FieldDef] = _daftar()

# Field profil yang boleh dipakai sebagai argumen fungsi `config:`
ARGUMEN_PROFIL = frozenset(PERTANYAAN)
