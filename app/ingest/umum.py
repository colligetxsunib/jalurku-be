"""Bagian bersama konverter ingest: error per baris dan kebijakan FR-D2.

FR-D2: tiap rule/dokumen wajib punya sumber_url, terakhir_diverifikasi, tahun_siklus.
Keputusan tim: `terakhir_diverifikasi` boleh kosong (status belum_diverifikasi) kecuali
REQUIRE_VERIFIED=true. Tanggal hanya diisi manusia, TIDAK PERNAH otomatis.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ErrorBaris:
    sumber: str  # nama berkas/tipe
    baris: int  # nomor baris data (mulai 1)
    pesan: str

    def ke_dict(self) -> dict[str, Any]:
        return {"sumber": self.sumber, "baris": self.baris, "pesan": self.pesan}


@dataclass(frozen=True)
class Kebijakan:
    require_verified: bool = False
    hari_ini: date = field(default_factory=date.today)


def teks(b: Mapping[str, Any], kolom: str) -> str:
    v = b.get(kolom)
    return "" if v is None else str(v).strip()


def parse_tanggal(nilai: str | None) -> date | None:
    """Kosong = belum diverifikasi. Tanggal TIDAK PERNAH diisi otomatis."""
    if nilai is None or not str(nilai).strip():
        return None
    return date.fromisoformat(str(nilai).strip())


def ambil_tanggal(
    b: Mapping[str, Any], k: Kebijakan, kolom: str = "terakhir_diverifikasi"
) -> date | None:
    mentah = teks(b, kolom)
    if not mentah:
        if k.require_verified:
            raise ValueError(f"{kolom} wajib diisi (REQUIRE_VERIFIED aktif)")
        return None
    try:
        tgl = date.fromisoformat(mentah)
    except ValueError as exc:
        raise ValueError(f"{kolom} harus berformat YYYY-MM-DD, bukan '{mentah}'") from exc
    if tgl > k.hari_ini + timedelta(days=1):
        raise ValueError(f"{kolom} ({tgl}) berada di masa depan")
    return tgl


def ambil_url(b: Mapping[str, Any], kolom: str = "sumber_url", *, wajib: bool = True) -> str | None:
    url = teks(b, kolom)
    if not url:
        if wajib:
            raise ValueError(f"{kolom} wajib diisi")
        return None
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"{kolom} harus berupa URL http(s), bukan '{url}'")
    return url


def ambil_int(
    b: Mapping[str, Any], kolom: str, *, wajib: bool = False, minimum: int | None = None
) -> int | None:
    mentah = teks(b, kolom)
    if not mentah:
        if wajib:
            raise ValueError(f"{kolom} wajib diisi")
        return None
    try:
        nilai = int(mentah)
    except ValueError as exc:
        raise ValueError(f"{kolom} harus bilangan bulat, bukan '{mentah}'") from exc
    if minimum is not None and nilai < minimum:
        raise ValueError(f"{kolom} harus >= {minimum}, bukan {nilai}")
    return nilai


def ambil_daftar(b: Mapping[str, Any], kolom: str) -> list[str] | None:
    mentah = teks(b, kolom)
    if not mentah:
        return None
    return [x.strip() for x in mentah.split("|") if x.strip()] or None


def proses_baris(
    baris: Iterable[Mapping[str, Any]],
    sumber: str,
    konversi: Callable[[Mapping[str, Any]], T],
) -> tuple[list[tuple[int, T]], list[ErrorBaris]]:
    """Terapkan `konversi` ke tiap baris. Mengembalikan [(nomor_baris, hasil)] dan error per baris.

    Error dikumpulkan, tidak berhenti dini, supaya data team melihat semua masalah sekaligus.
    """
    hasil: list[tuple[int, T]] = []
    galat: list[ErrorBaris] = []
    for no, b in enumerate(baris, start=1):
        try:
            hasil.append((no, konversi(b)))
        except (ValueError, KeyError, TypeError) as exc:
            galat.append(ErrorBaris(sumber, no, str(exc)))
    return hasil, galat
