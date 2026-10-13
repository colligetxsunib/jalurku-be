"""Pagar keluaran LLM: narasi tidak boleh memuat angka/persentase yang tidak ada di fakta mesin aturan."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_ANGKA = re.compile(r"\d+(?:[.,]\d+)?")
_PERSEN = re.compile(
    r"\d\s*%|\bpersen\b|\bpeluang\b|\bprobabilitas\b|\bkemungkinan diterima\b", re.IGNORECASE
)


def _angka_dalam(teks: str) -> set[str]:
    return {a.replace(",", ".") for a in _ANGKA.findall(teks)}


def angka_tidak_dikenal(teks: str, fakta: Mapping[str, Any]) -> list[str]:
    """Angka di `teks` yang tidak muncul di `fakta` (dibandingkan sebagai token angka)."""
    ada = _angka_dalam(json.dumps(fakta, ensure_ascii=False, default=str))
    # angka bulat dari float di fakta (mis. 0.83 -> '0.83'; 620.0 -> '620')
    for nilai in list(ada):
        if nilai.endswith(".0"):
            ada.add(nilai[:-2])
    return sorted(a for a in _angka_dalam(teks) if a not in ada)


def keluaran_aman(teks: str, fakta: Mapping[str, Any]) -> tuple[bool, str | None]:
    """(aman, alasan_ditolak). Tolak bila ada klaim persentase/peluang atau angka di luar fakta."""
    if _PERSEN.search(teks):
        return False, "memuat klaim persentase atau peluang"
    asing = angka_tidak_dikenal(teks, fakta)
    if asing:
        return False, f"memuat angka di luar fakta mesin aturan: {', '.join(asing[:5])}"
    return True, None


# ----------------------------------------------------------------------------- narasi ringkasan

MAKS_PANJANG_NARASI = 1200
_KATEGORI = re.compile(r"\b(reach|match|safe)\b", re.IGNORECASE)
_BATAS_KALIMAT = re.compile(r"(?<=[.!?;])\s+|\n+")
_MARKUP = re.compile(r"[<>]")


def kategori_tidak_sesuai(teks: str, pilihan: Sequence[Mapping[str, Any]]) -> list[str]:
    """Kalimat yang menyebut sebuah prodi bersama kategori reach/match/safe yang bukan hasil mesin aturan.

    `pilihan` = [{"prodi": nama, "kategori": ...}]. Per kalimat: kategori yang disebut harus
    termasuk kategori prodi-prodi yang namanya disebut di kalimat itu. Kalimat tanpa nama prodi tidak
    bisa dipetakan sehingga tidak diperiksa. Nama prodi kembar (mis. S1 dan D3) dilonggarkan ke
    gabungan kategori mereka.
    """
    salah: list[str] = []
    for kalimat in _BATAS_KALIMAT.split(teks):
        disebut = {m.lower() for m in _KATEGORI.findall(kalimat)}
        if not disebut:
            continue
        rendah = kalimat.lower()
        cocok = [p for p in pilihan if str(p.get("prodi", "")).lower() in rendah and p.get("prodi")]
        if not cocok:
            continue
        diizinkan = {str(p.get("kategori")).lower() for p in cocok}
        if not disebut <= diizinkan:
            salah.append(kalimat.strip())
    return salah


def narasi_aman(teks: str, fakta: Mapping[str, Any]) -> tuple[bool, str | None]:
    """Pagar narasi ringkasan: `keluaran_aman` + kategori sesuai mesin aturan + bentuk teks polos.

    Narasi hanya boleh menyusun kalimat dari fakta mesin aturan. Bila ditolak, pemanggil memakai
    narasi template.
    """
    if not teks.strip():
        return False, "kosong"
    if len(teks) > MAKS_PANJANG_NARASI:
        return False, "terlalu panjang (kemungkinan terpotong)"
    if _MARKUP.search(teks):
        return False, "memuat tag/markup"
    aman, alasan = keluaran_aman(teks, fakta)
    if not aman:
        return False, alasan
    pilihan = [p for j in fakta.get("jalur", []) for p in j.get("pilihan", [])]
    salah = kategori_tidak_sesuai(teks, pilihan)
    if salah:
        return False, f"kategori tidak sesuai hasil mesin aturan: {salah[0][:80]}"
    return True, None
