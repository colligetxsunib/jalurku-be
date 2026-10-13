"""Konversi `profesi.csv` menjadi baris `profesi` (contoh profesi per rumpun untuk /explore).

Kolom: rumpun, nama (wajib); id, deskripsi (opsional; id dibuat dari rumpun + nama bila kosong).
Tabel `profesi` belum punya kolom verifikasi, jadi baris tidak membawa tanggal verifikasi.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.ingest.umum import ErrorBaris, proses_baris, teks

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _profesi(b: Mapping[str, Any]) -> dict[str, Any]:
    rumpun, nama = teks(b, "rumpun"), teks(b, "nama")
    if not rumpun or not nama:
        raise ValueError("rumpun dan nama wajib diisi")
    if len(nama) > 200 or len(rumpun) > 100:
        raise ValueError("rumpun maksimal 100 karakter dan nama maksimal 200 karakter")
    pid = teks(b, "id") or f"{_slug(rumpun)}-{_slug(nama)}"[:64].strip("-")
    if not _ID.match(pid):
        raise ValueError("id hanya boleh huruf kecil, angka, '-' dan '_' (maksimal 64 karakter)")
    return {"id": pid, "rumpun": rumpun, "nama": nama, "deskripsi": teks(b, "deskripsi") or None}


def profesi_dari_baris(
    baris: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[ErrorBaris]]:
    hasil, galat = proses_baris(baris, "profesi", _profesi)
    unik: dict[str, dict[str, Any]] = {}
    for no, item in hasil:
        if item["id"] in unik:
            galat.append(ErrorBaris("profesi", no, f"id '{item['id']}' duplikat dalam satu batch"))
            continue
        unik[item["id"]] = item
    return list(unik.values()), sorted(galat, key=lambda e: e.baris)
