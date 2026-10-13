"""Konversi baris `rule_gate.csv` (+ `dokumen_wajib.csv`) menjadi objek Rules, dengan validasi."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.expr import validasi_syarat
from app.domain.gate import Rules, Syarat
from app.ingest.umum import (
    ErrorBaris,
    Kebijakan,
    ambil_tanggal,
    ambil_url,
    parse_tanggal,
    teks,
)

JALUR_VALID = ("SNBP", "SNBT")
__all__ = ["ErrorBaris", "JALUR_VALID", "rules_dari_baris", "dokumen_wajib_dari_baris"]


def _syarat(b: Mapping[str, Any], kebijakan: Kebijakan | None) -> tuple[str, int, Syarat]:
    jalur = teks(b, "jalur")
    if jalur not in JALUR_VALID:
        raise ValueError(f"jalur harus salah satu dari {JALUR_VALID}, bukan '{jalur}'")
    mentah_tahun = teks(b, "tahun_siklus")
    if not mentah_tahun.isdigit():
        raise ValueError("tahun_siklus wajib berupa tahun, mis. 2026")
    sid = teks(b, "syarat_id")
    if not sid:
        raise ValueError("syarat_id wajib diisi")
    alasan = teks(b, "alasan_gagal")
    if not alasan:
        raise ValueError("alasan_gagal wajib diisi")
    field, op, nilai = teks(b, "field"), teks(b, "op"), teks(b, "nilai")
    masalah = validasi_syarat(field, op, nilai)
    if masalah:
        raise ValueError("; ".join(masalah))
    if kebijakan is None:
        sumber = teks(b, "sumber_url") or None
        tanggal = parse_tanggal(teks(b, "terakhir_diverifikasi"))
    else:
        sumber = ambil_url(b)
        tanggal = ambil_tanggal(b, kebijakan)
    return (
        jalur,
        int(mentah_tahun),
        Syarat(sid, field, op, nilai, alasan, sumber, tanggal),
    )


def rules_dari_baris(
    baris: Iterable[Mapping[str, Any]],
    *,
    sumber: str = "rule_gate",
    kebijakan: Kebijakan | None = None,
) -> tuple[list[Rules], list[ErrorBaris]]:
    """Kelompokkan per (jalur, tahun_siklus). Error dikumpulkan per baris.

    Tanpa `kebijakan` pemeriksaan FR-D2 (sumber_url wajib, tanggal) dilewati; ingest selalu
    memberikan kebijakan.
    """
    galat: list[ErrorBaris] = []
    kelompok: dict[tuple[str, int], list[Syarat]] = defaultdict(list)
    terlihat: set[tuple[str, int, str]] = set()

    for no, b in enumerate(baris, start=1):
        try:
            jalur, tahun, s = _syarat(b, kebijakan)
            if (jalur, tahun, s.id) in terlihat:
                raise ValueError(f"syarat_id '{s.id}' duplikat")
            terlihat.add((jalur, tahun, s.id))
            kelompok[(jalur, tahun)].append(s)
        except (ValueError, KeyError) as exc:
            galat.append(ErrorBaris(sumber, no, str(exc)))

    hasil: list[Rules] = []
    for (jalur, tahun), daftar in sorted(kelompok.items()):
        tanggal = [s.terakhir_diverifikasi for s in daftar]
        urls = {s.sumber_url for s in daftar if s.sumber_url}
        hasil.append(
            Rules(
                jalur=jalur,
                tahun_siklus=tahun,
                syarat=tuple(daftar),
                sumber_url=next(iter(urls)) if len(urls) == 1 else None,
                # Rule dianggap terverifikasi hanya bila SEMUA syaratnya terverifikasi.
                terakhir_diverifikasi=None if any(t is None for t in tanggal) else min(tanggal),
            )
        )
    return hasil, galat


def dokumen_wajib_dari_baris(
    baris: Iterable[Mapping[str, Any]],
    *,
    sumber: str = "dokumen_wajib",
    kebijakan: Kebijakan,
) -> tuple[list[tuple[int, str, int | None, dict[str, Any]]], list[ErrorBaris]]:
    """Kembalikan (nomor_baris, jalur, tahun_siklus|None, {nama, sumber_url, terakhir_diverifikasi})."""
    hasil: list[tuple[int, str, int | None, dict[str, Any]]] = []
    galat: list[ErrorBaris] = []
    for no, b in enumerate(baris, start=1):
        try:
            jalur = teks(b, "jalur")
            if jalur not in JALUR_VALID:
                raise ValueError(f"jalur harus salah satu dari {JALUR_VALID}, bukan '{jalur}'")
            nama = teks(b, "nama_dokumen")
            if not nama:
                raise ValueError("nama_dokumen wajib diisi")
            tahun_mentah = teks(b, "tahun_siklus")
            if tahun_mentah and not tahun_mentah.isdigit():
                raise ValueError("tahun_siklus harus berupa tahun")
            tanggal = ambil_tanggal(b, kebijakan)
            hasil.append(
                (
                    no,
                    jalur,
                    int(tahun_mentah) if tahun_mentah else None,
                    {
                        "nama": nama,
                        "sumber_url": ambil_url(b),
                        "terakhir_diverifikasi": tanggal.isoformat() if tanggal else None,
                    },
                )
            )
        except ValueError as exc:
            galat.append(ErrorBaris(sumber, no, str(exc)))
    return hasil, galat
