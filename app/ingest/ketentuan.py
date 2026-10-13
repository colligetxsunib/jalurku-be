"""Konversi baris `config_ketentuan.csv`. Komposisi pilihan SNBT diurai menjadi struktur."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.ingest.umum import (
    ErrorBaris,
    Kebijakan,
    ambil_tanggal,
    ambil_url,
    proses_baris,
    teks,
)

JALUR_KETENTUAN = ("SNBP", "SNBT", "ALL")

_RE_KOMPOSISI_KEY = re.compile(r"^komposisi_pilihan_(\d+)$")
_RE_AKADEMIK = re.compile(r"(\d+)\s*akademik", re.IGNORECASE)
_RE_VOKASI = re.compile(r"(\d+)\s*vokasi", re.IGNORECASE)
_RE_MIN_D3 = re.compile(r"min(?:imal)?\s*(\d+)\s*D3", re.IGNORECASE)


def parse_komposisi(nilai: str, jumlah_pilihan: int) -> list[dict[str, int]]:
    """Urai '2 akademik+1 vokasi | 3 vokasi dengan minimal 1 D3' menjadi daftar komposisi sah.

    Setiap alternatif: {"akademik": n, "vokasi": n, "min_d3": n}. Total harus sama dengan
    jumlah pilihan pada nama kunci.
    """
    hasil: list[dict[str, int]] = []
    for alternatif in (x.strip() for x in nilai.split("|") if x.strip()):
        m_ak, m_vo, m_d3 = (
            _RE_AKADEMIK.search(alternatif),
            _RE_VOKASI.search(alternatif),
            _RE_MIN_D3.search(alternatif),
        )
        if m_ak is None and m_vo is None:
            raise ValueError(f"komposisi tidak dapat dibaca: '{alternatif}'")
        akademik = int(m_ak.group(1)) if m_ak else 0
        vokasi = int(m_vo.group(1)) if m_vo else 0
        min_d3 = int(m_d3.group(1)) if m_d3 else 0
        if akademik + vokasi != jumlah_pilihan:
            raise ValueError(
                f"komposisi '{alternatif}' berjumlah {akademik + vokasi}, seharusnya {jumlah_pilihan}"
            )
        if min_d3 > vokasi:
            raise ValueError(
                f"minimal D3 ({min_d3}) melebihi jumlah vokasi ({vokasi}): '{alternatif}'"
            )
        hasil.append({"akademik": akademik, "vokasi": vokasi, "min_d3": min_d3})
    if not hasil:
        raise ValueError("komposisi kosong")
    return hasil


def _harus_angka(key: str) -> bool:
    return (
        key in {"max_pilihan_prodi", "tahun_acuan_pendaftaran"}
        or key.startswith(("kuota_", "komponen_seleksi_"))
        and (key.endswith("_persen") or "_persen_" in key)
    )


def _konversi(b: Mapping[str, Any], kebijakan: Kebijakan) -> dict[str, Any]:
    key, jalur = teks(b, "key"), teks(b, "jalur")
    if not key:
        raise ValueError("key wajib diisi")
    if jalur not in JALUR_KETENTUAN:
        raise ValueError(f"jalur harus salah satu dari {JALUR_KETENTUAN}, bukan '{jalur}'")
    tahun = teks(b, "tahun_siklus")
    if not tahun.isdigit():
        raise ValueError("tahun_siklus wajib berupa tahun, mis. 2026")
    nilai = teks(b, "nilai")
    if not nilai:
        raise ValueError("nilai wajib diisi")
    if _harus_angka(key):
        try:
            float(nilai)
        except ValueError as exc:
            raise ValueError(f"nilai untuk '{key}' harus angka, bukan '{nilai}'") from exc

    terstruktur: Any = None
    if (m := _RE_KOMPOSISI_KEY.match(key)) is not None:
        terstruktur = parse_komposisi(nilai, int(m.group(1)))
    elif key == "komposisi_pilihan_1_2":
        if nilai.lower() != "bebas":
            raise ValueError("komposisi_pilihan_1_2 hanya mendukung nilai 'bebas'")
        terstruktur = "bebas"

    return {
        "key": key,
        "jalur": jalur,
        "tahun_siklus": int(tahun),
        "nilai": nilai,
        "nilai_terstruktur": terstruktur,
        "keterangan": teks(b, "keterangan") or None,
        "sumber_url": ambil_url(b),
        "terakhir_diverifikasi": ambil_tanggal(b, kebijakan),
    }


def ketentuan_dari_baris(
    baris: Iterable[Mapping[str, Any]], kebijakan: Kebijakan, *, sumber: str = "config_ketentuan"
) -> tuple[list[dict[str, Any]], list[ErrorBaris]]:
    hasil, galat = proses_baris(baris, sumber, lambda b: _konversi(b, kebijakan))
    terlihat: set[tuple[str, str, int]] = set()
    unik: list[dict[str, Any]] = []
    for no, item in hasil:
        kunci = (item["key"], item["jalur"], item["tahun_siklus"])
        if kunci in terlihat:
            galat.append(ErrorBaris(sumber, no, f"ketentuan {kunci} duplikat dalam satu batch"))
            continue
        terlihat.add(kunci)
        unik.append(item)
    return unik, galat
