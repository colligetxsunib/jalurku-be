"""Konversi `dokumen_rag_metadata.csv` menjadi baris `dokumen_sumber`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.ingest.umum import ErrorBaris, Kebijakan, ambil_tanggal, ambil_url, proses_baris, teks


def _dokumen(b: Mapping[str, Any], k: Kebijakan) -> dict[str, Any]:
    dokumen_id = teks(b, "dokumen_id")
    if not dokumen_id:
        raise ValueError("dokumen_id wajib diisi")
    judul, jenis = teks(b, "judul"), teks(b, "jenis")
    if not judul or not jenis:
        raise ValueError("judul dan jenis wajib diisi")
    tahun = teks(b, "tahun_siklus")
    if not tahun.isdigit():
        raise ValueError("tahun_siklus wajib berupa tahun, mis. 2026")
    return {
        "id": dokumen_id,
        "judul": judul,
        "url": ambil_url(b, "url"),
        "jenis": jenis,
        "tahun_siklus": int(tahun),
        "terakhir_diverifikasi": ambil_tanggal(b, k),
    }


def dokumen_dari_baris(
    baris: Iterable[Mapping[str, Any]], kebijakan: Kebijakan
) -> tuple[list[dict[str, Any]], list[ErrorBaris]]:
    hasil, galat = proses_baris(baris, "dokumen", lambda b: _dokumen(b, kebijakan))
    unik: dict[str, dict[str, Any]] = {}
    for no, item in hasil:
        if item["id"] in unik:
            galat.append(
                ErrorBaris("dokumen", no, f"dokumen_id '{item['id']}' duplikat dalam satu batch")
            )
            continue
        unik[item["id"]] = item
    return list(unik.values()), sorted(galat, key=lambda e: e.baris)
