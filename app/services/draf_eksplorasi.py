"""Data eksplorasi DRAF (belum terverifikasi): tag_minat, mapel_penentu per prodi dan contoh profesi.

Dibaca dari data/draft/*.csv, TERPISAH dari CSV utama dan dari tabel basis data. Berkas ini tidak pernah
memuat `terakhir_diverifikasi`, dan setiap barisnya wajib berlabel "draf". /explore memakainya hanya bila
data resmi (prodi.tag_minat, prodi.mapel_penentu, tabel profesi) kosong, dan menandai hasilnya sebagai draf.
Berkas tidak ada = tidak ada draf (bukan error).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import ConfigError

NAMA_PRODI = "prodi_eksplorasi_draf.csv"
NAMA_PROFESI = "profesi_draf.csv"
LABEL_DRAF = "draf, belum terverifikasi"
KOLOM_DILARANG = {"terakhir_diverifikasi", "diverifikasi_oleh"}


@dataclass(frozen=True)
class DrafEksplorasi:
    tag_minat: dict[str, list[str]] = field(
        default_factory=dict
    )  # prodi_id -> kode RIASEC (dimensi)
    mapel: dict[str, list[str]] = field(default_factory=dict)  # prodi_id -> mapel penentu
    profesi: dict[str, list[str]] = field(default_factory=dict)  # rumpun -> contoh profesi

    @property
    def ada(self) -> bool:
        return bool(self.tag_minat or self.mapel or self.profesi)


def _daftar(mentah: str) -> list[str]:
    return [x.strip() for x in (mentah or "").split("|") if x.strip()]


def _baca(path: Path, wajib: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        pembaca = csv.DictReader(f)
        kolom = set(pembaca.fieldnames or [])
        if not wajib <= kolom:
            raise ConfigError(
                f"{path.name}: kolom wajib hilang: {', '.join(sorted(wajib - kolom))}"
            )
        if kolom & KOLOM_DILARANG:
            raise ConfigError(
                f"{path.name}: berkas draf tidak boleh memuat {', '.join(sorted(kolom & KOLOM_DILARANG))}"
            )
        baris = list(pembaca)
    for i, b in enumerate(baris, start=2):
        if "draf" not in (b.get("status") or "").lower():
            raise ConfigError(f"{path.name} baris {i}: kolom status wajib berlabel '{LABEL_DRAF}'")
    return baris


def muat_draf(folder: str | Path, dimensi: list[str]) -> DrafEksplorasi:
    """Muat draf bila ada. Isi yang tidak valid (dimensi tak dikenal, label hilang) = ConfigError."""
    folder = Path(folder)
    tag: dict[str, list[str]] = {}
    mapel: dict[str, list[str]] = {}
    profesi: dict[str, list[str]] = {}

    p_prodi = folder / NAMA_PRODI
    if p_prodi.is_file():
        for i, b in enumerate(
            _baca(p_prodi, {"prodi_id", "tag_minat", "mapel_penentu", "status"}), 2
        ):
            pid = (b["prodi_id"] or "").strip()
            if not pid:
                raise ConfigError(f"{NAMA_PRODI} baris {i}: prodi_id kosong")
            asing = sorted(set(_daftar(b["tag_minat"])) - set(dimensi))
            if asing:
                raise ConfigError(
                    f"{NAMA_PRODI} baris {i}: tag_minat bukan kode RIASEC yang dikenal: {', '.join(asing)}"
                )
            if _daftar(b["tag_minat"]):
                tag[pid] = _daftar(b["tag_minat"])
            if _daftar(b["mapel_penentu"]):
                mapel[pid] = _daftar(b["mapel_penentu"])

    p_profesi = folder / NAMA_PROFESI
    if p_profesi.is_file():
        for b in _baca(p_profesi, {"rumpun", "nama", "status"}):
            if (b["rumpun"] or "").strip() and (b["nama"] or "").strip():
                profesi.setdefault(b["rumpun"].strip(), []).append(b["nama"].strip())
    return DrafEksplorasi(tag_minat=tag, mapel=mapel, profesi=profesi)
