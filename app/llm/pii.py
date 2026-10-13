"""Penyaring PII sederhana (PRD bagian 10 dan 15): email, nomor telepon, deret angka panjang.

Dipakai sebelum teks bebas disimpan (query_logs), di-cache, atau dikirim ke LLM. Ini penyaring
SEDERHANA, bukan jaminan: nama orang tidak bisa dideteksi, jadi UI tetap harus memperingatkan siswa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Nomor telepon Indonesia: +62 / 62 / 0 diikuti 8xx, dengan pemisah spasi/titik/strip opsional.
_TELEPON = re.compile(r"(?<!\d)(?:\+?62|0)[\s.\-]?8\d{1,3}(?:[\s.\-]?\d{2,5}){2,3}(?!\d)")
# Deret angka >= 8 digit berurutan (NIK 16 digit, NISN 10 digit, nomor lain).
_ANGKA_PANJANG = re.compile(r"(?<!\d)\d{8,}(?!\d)")
# Deret angka dipisah spasi/strip/titik dengan kelompok 3-5 digit, total >= 9 digit (NIK berspasi).
_ANGKA_KELOMPOK = re.compile(r"(?<!\d)\d{3,5}(?:[\s\-]\d{3,5}){2,}(?!\d)")


@dataclass(frozen=True)
class HasilPII:
    teks: str
    ditemukan: tuple[str, ...]

    @property
    def ada(self) -> bool:
        return bool(self.ditemukan)


def saring_pii(teks: str) -> HasilPII:
    """Ganti PII dengan penanda ([email], [telepon], [angka]). Idempoten."""
    ditemukan: list[str] = []

    def ganti(pola: re.Pattern[str], penanda: str, jenis: str, s: str) -> str:
        def sub(_: re.Match[str]) -> str:
            if jenis not in ditemukan:
                ditemukan.append(jenis)
            return penanda

        return pola.sub(sub, s)

    hasil = ganti(_EMAIL, "[email]", "email", teks)
    hasil = ganti(_TELEPON, "[telepon]", "telepon", hasil)
    hasil = ganti(_ANGKA_PANJANG, "[angka]", "angka_panjang", hasil)
    hasil = ganti(_ANGKA_KELOMPOK, "[angka]", "angka_panjang", hasil)
    return HasilPII(hasil, tuple(ditemukan))


def normalisasi_pertanyaan(teks: str) -> str:
    """Bentuk kanonik untuk kunci cache: NFKC, huruf kecil, tanpa tanda baca, spasi tunggal."""
    t = unicodedata.normalize("NFKC", teks).casefold()
    t = re.sub(r"[^\w\s\[\]]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())
