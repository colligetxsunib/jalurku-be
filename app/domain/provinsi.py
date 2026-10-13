"""Daftar baku 38 provinsi (FR-P2). Dipakai validasi profil dan ingest PTN."""

from __future__ import annotations

PROVINSI_BAKU: tuple[str, ...] = (
    "Aceh",
    "Sumatera Utara",
    "Sumatera Barat",
    "Riau",
    "Kepulauan Riau",
    "Jambi",
    "Sumatera Selatan",
    "Kepulauan Bangka Belitung",
    "Bengkulu",
    "Lampung",
    "DKI Jakarta",
    "Jawa Barat",
    "Banten",
    "Jawa Tengah",
    "DI Yogyakarta",
    "Jawa Timur",
    "Bali",
    "Nusa Tenggara Barat",
    "Nusa Tenggara Timur",
    "Kalimantan Barat",
    "Kalimantan Tengah",
    "Kalimantan Selatan",
    "Kalimantan Timur",
    "Kalimantan Utara",
    "Sulawesi Utara",
    "Gorontalo",
    "Sulawesi Tengah",
    "Sulawesi Barat",
    "Sulawesi Selatan",
    "Sulawesi Tenggara",
    "Maluku",
    "Maluku Utara",
    "Papua",
    "Papua Barat",
    "Papua Barat Daya",
    "Papua Selatan",
    "Papua Tengah",
    "Papua Pegunungan",
)

_PETA = {p.casefold(): p for p in PROVINSI_BAKU}


def normalisasi_provinsi(teks: str | None) -> str | None:
    """Kembalikan nama baku (abaikan huruf besar/kecil dan spasi ganda) atau None bila tidak dikenal."""
    if teks is None:
        return None
    return _PETA.get(" ".join(teks.split()).casefold())
