"""Pemotongan teks dokumen menjadi chunk (PRD bagian 9): ± 500-1000 karakter, overlap 100-200.

Fungsi murni. Chunk TIDAK melintasi halaman supaya metadata halaman (untuk sitasi) selalu tepat.
Pemotongan mengikuti batas kalimat; kalimat yang lebih panjang dari batas dipotong per kata.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

_KALIMAT = re.compile(r"(?<=[.!?])\s+")
MIN_ISI = 40  # chunk lebih pendek dari ini dianggap noise (nomor halaman, header)


class ChunkTerlaluBesar(ValueError):
    """Chunk melebihi batas token model embedding (2.048 token untuk gemini-embedding-001)."""


@dataclass(frozen=True)
class Chunk:
    urutan: int
    halaman: int | None
    teks: str


def perkiraan_token(teks: str) -> int:
    """Perkiraan konservatif (≈ 3 karakter per token untuk teks Indonesia)."""
    return math.ceil(len(teks) / 3)


def rapikan(teks: str) -> str:
    """Satukan baris hasil ekstraksi PDF dalam satu paragraf; spasi ganda dibuang."""
    teks = teks.replace("\r", "\n").replace("\u00a0", " ")
    teks = re.sub(r"-\n(?=[a-z])", "", teks)  # kata terpenggal di akhir baris
    paragraf = re.split(r"\n\s*\n", teks)
    return " ".join(" ".join(p.split()) for p in paragraf if p.strip())


def _pecah_kata(kalimat: str, maks: int) -> list[str]:
    bagian: list[str] = []
    saat_ini = ""
    for kata in kalimat.split():
        while len(kata) > maks:  # token tunggal sangat panjang (URL, dsb.)
            if saat_ini:
                bagian.append(saat_ini)
                saat_ini = ""
            bagian.append(kata[:maks])
            kata = kata[maks:]
        if saat_ini and len(saat_ini) + 1 + len(kata) > maks:
            bagian.append(saat_ini)
            saat_ini = kata
        else:
            saat_ini = f"{saat_ini} {kata}".strip()
    if saat_ini:
        bagian.append(saat_ini)
    return bagian


def _unit(teks: str, maks: int) -> list[str]:
    unit: list[str] = []
    for kalimat in _KALIMAT.split(teks):
        kalimat = kalimat.strip()
        if not kalimat:
            continue
        unit.extend([kalimat] if len(kalimat) <= maks else _pecah_kata(kalimat, maks))
    return unit


def _ekor(teks: str, n: int) -> str:
    """Potongan akhir ≤ n karakter yang dimulai di batas kata (untuk overlap)."""
    if n <= 0 or len(teks) <= n:
        return teks if n > 0 else ""
    potongan = teks[-n:]
    spasi = potongan.find(" ")
    return potongan[spasi + 1 :] if spasi != -1 else ""


def potong_halaman(teks: str, *, minimum: int, maksimum: int, overlap: int) -> list[str]:
    if minimum > maksimum:
        raise ValueError("ukuran minimum tidak boleh melebihi maksimum")
    if overlap >= maksimum:
        raise ValueError("overlap harus lebih kecil dari ukuran maksimum")
    bersih = rapikan(teks)
    if not bersih:
        return []

    chunks: list[str] = []
    saat_ini = ""
    baru = ""  # bagian di chunk berjalan yang bukan overlap
    for u in _unit(bersih, maksimum):
        if saat_ini and len(saat_ini) + 1 + len(u) > maksimum:
            chunks.append(saat_ini)
            ekor = _ekor(saat_ini, overlap)
            mulai = f"{ekor} {u}".strip() if ekor else u
            if len(mulai) > maksimum:  # overlap + unit tidak muat: buang overlap
                mulai, ekor = u, ""
            saat_ini, baru = mulai, u
        else:
            saat_ini = f"{saat_ini} {u}".strip() if saat_ini else u
            baru = f"{baru} {u}".strip() if baru else u
    if saat_ini:
        if chunks and len(saat_ini) < minimum and len(chunks[-1]) + 1 + len(baru) <= maksimum:
            chunks[-1] = f"{chunks[-1]} {baru}"  # ekor pendek digabung ke chunk sebelumnya
        else:
            chunks.append(saat_ini)
    return chunks


def potong_dokumen(
    halaman: Sequence[tuple[int | None, str]],
    *,
    minimum: int,
    maksimum: int,
    overlap: int,
    maks_token: int = 2048,
) -> list[Chunk]:
    """`halaman` = [(nomor_halaman | None, teks)]. Urutan chunk berlanjut lintas halaman."""
    hasil: list[Chunk] = []
    for no, teks in halaman:
        for potongan in potong_halaman(teks, minimum=minimum, maksimum=maksimum, overlap=overlap):
            if len(potongan) < MIN_ISI:
                continue
            if perkiraan_token(potongan) > maks_token:
                raise ChunkTerlaluBesar(
                    f"chunk berukuran ±{perkiraan_token(potongan)} token melebihi batas {maks_token}"
                    + (f" (halaman {no})" if no is not None else "")
                )
            hasil.append(Chunk(urutan=len(hasil), halaman=no, teks=potongan))
    return hasil
