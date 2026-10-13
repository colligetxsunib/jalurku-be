"""Konversi `acuan_skor_snbt.csv` (acuan skor rendah/tinggi per prodi, dari data tahun lalu)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.ingest.umum import ErrorBaris, Kebijakan, ambil_tanggal, ambil_url, proses_baris, teks


def _angka(b: Mapping[str, Any], kolom: str) -> float:
    mentah = teks(b, kolom)
    if not mentah:
        raise ValueError(f"{kolom} wajib diisi")
    try:
        return float(mentah)
    except ValueError as exc:
        raise ValueError(f"{kolom} harus angka, bukan '{mentah}'") from exc


def _acuan(b: Mapping[str, Any], k: Kebijakan) -> dict[str, Any]:
    prodi_id = teks(b, "prodi_id")
    if not prodi_id:
        raise ValueError("prodi_id wajib diisi")
    jalur = teks(b, "jalur").upper()
    if jalur not in ("SNBP", "SNBT"):
        raise ValueError(f"jalur harus SNBP atau SNBT, bukan '{jalur}'")
    tahun = teks(b, "tahun")
    if not tahun.isdigit():
        raise ValueError("tahun wajib berupa tahun, mis. 2025")
    rendah, tinggi = _angka(b, "rendah"), _angka(b, "tinggi")
    if rendah > tinggi:
        raise ValueError(f"rendah ({rendah}) tidak boleh lebih besar dari tinggi ({tinggi})")
    return {
        "prodi_id": prodi_id,
        "jalur": jalur,
        "tahun": int(tahun),
        "rendah": rendah,
        "tinggi": tinggi,
        "sumber_url": ambil_url(b),
        "terakhir_diverifikasi": ambil_tanggal(b, k),
    }


def acuan_dari_baris(
    baris: Iterable[Mapping[str, Any]], kebijakan: Kebijakan
) -> tuple[list[dict[str, Any]], list[ErrorBaris]]:
    hasil, galat = proses_baris(baris, "acuan_skor", lambda b: _acuan(b, kebijakan))
    unik: dict[tuple[str, str, int], dict[str, Any]] = {}
    for no, item in hasil:
        kunci = (item["prodi_id"], item["jalur"], item["tahun"])
        if kunci in unik:
            galat.append(ErrorBaris("acuan_skor", no, f"acuan {kunci} duplikat dalam satu batch"))
            continue
        item["_baris"] = no  # dipakai service untuk error referensi, dibuang sebelum disimpan
        unik[kunci] = item
    return list(unik.values()), sorted(galat, key=lambda e: e.baris)
