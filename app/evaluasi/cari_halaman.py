"""Mencari halaman PDF tempat sebuah jawaban golden set tertulis (mengisi kolom `halaman`).

Jawaban golden set adalah parafrasa, bukan kutipan, jadi pencocokan dilakukan atas kata bermakna:
huruf kecil, tanpa kata sambung, angka dan kata bilangan disamakan ("dua" = "2", "%" = "persen").
Dua ukuran per halaman:
- `kata`: porsi kata bermakna jawaban yang muncul di halaman,
- `frasa`: porsi pasangan kata berurutan jawaban yang muncul berurutan di halaman.

Status hasil (hanya `ditemukan` yang boleh mengisi kolom halaman secara otomatis):
- `ditemukan`: frasa dan kata cukup tinggi, halaman cukup yakin;
- `perkiraan`: kata cukup tinggi tetapi frasa rendah. Halaman terbaik dilaporkan, TIDAK diisi, perlu dicek manusia;
- `tidak_ditemukan`: tidak ada halaman yang cukup mirip.
Fungsi murni, tanpa I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

STOP = frozenset(
    "yang dan atau di ke dari untuk dengan adalah itu ini pada dalam jika bila saya kamu aku bisa "
    "boleh bisakah bolehkah apakah apa berapa bagaimana harus ada semua para serta oleh akan juga "
    "sebagai bagi hanya telah sudah per dapat dengan nya mana sesuai agar karena maka tetapi namun "
    "ya bukan sekolah anda kalau".split()
)
BILANGAN = {
    "satu": "1",
    "dua": "2",
    "tiga": "3",
    "empat": "4",
    "lima": "5",
    "enam": "6",
    "tujuh": "7",
    "delapan": "8",
    "sembilan": "9",
    "sepuluh": "10",
}
AMBANG_KATA_DITEMUKAN = 0.80
AMBANG_FRASA_DITEMUKAN = 0.55
AMBANG_KATA_PERKIRAAN = 0.60


def token(teks: str) -> list[str]:
    """Kata bermakna, berurutan. 'tidak' sengaja dipertahankan karena membalik arti jawaban."""
    teks = teks.lower().replace("%", " persen ")
    kata = re.findall(r"[a-z0-9]+", teks)
    hasil = []
    for k in kata:
        k = BILANGAN.get(k, k)
        if k in STOP or (len(k) < 2 and not k.isdigit()):
            continue
        hasil.append(k)
    return hasil


def _bigram(kata: Sequence[str]) -> set[tuple[str, str]]:
    return set(zip(kata, kata[1:], strict=False))


@dataclass(frozen=True)
class HasilCari:
    status: str  # ditemukan | perkiraan | tidak_ditemukan
    halaman: int | None  # halaman terbaik (juga untuk perkiraan), None bila tidak ada kandidat
    kata: float
    frasa: float

    def catatan(self) -> str:
        if self.status == "ditemukan":
            return f"ditemukan (kata {self.kata:.2f}, frasa {self.frasa:.2f})"
        if self.status == "perkiraan":
            return f"perkiraan hal. {self.halaman} (kata {self.kata:.2f}, frasa {self.frasa:.2f}), cek manual"
        return f"tidak_ditemukan (terdekat hal. {self.halaman}, kata {self.kata:.2f})"


def cari(jawaban: str, halaman: Sequence[tuple[int | None, str]]) -> HasilCari:
    """`halaman` = [(nomor, teks)] dari app.rag.extract.ekstrak. Halaman tanpa nomor dilewati."""
    kunci = token(jawaban)
    if not kunci:
        return HasilCari("tidak_ditemukan", None, 0.0, 0.0)
    angka = {k for k in kunci if k.isdigit()}
    kata_kunci = set(kunci)
    frasa_kunci = _bigram(kunci)

    terbaik: tuple[float, float, int] | None = None  # (kata, frasa, nomor halaman)
    for nomor, teks in halaman:
        if nomor is None:
            continue
        kata_hal = token(teks)
        himpunan = set(kata_hal)
        kata = len(kata_kunci & himpunan) / len(kata_kunci)
        frasa = len(frasa_kunci & _bigram(kata_hal)) / len(frasa_kunci) if frasa_kunci else 0.0
        # Angka dalam jawaban harus ada di halaman; kalau tidak, kata dikurangi (angka = fakta inti)
        if angka and not angka <= himpunan:
            kata *= 0.5
        # Skor terbaik = kata + frasa; seri dimenangkan halaman bernomor lebih kecil
        if terbaik is None or (kata + frasa) > (terbaik[0] + terbaik[1]):
            terbaik = (kata, frasa, nomor)
    if terbaik is None:
        return HasilCari("tidak_ditemukan", None, 0.0, 0.0)

    kata, frasa, nomor_terbaik = terbaik
    if kata >= AMBANG_KATA_DITEMUKAN and frasa >= AMBANG_FRASA_DITEMUKAN:
        return HasilCari("ditemukan", nomor_terbaik, kata, frasa)
    if kata >= AMBANG_KATA_PERKIRAAN:
        return HasilCari("perkiraan", nomor_terbaik, kata, frasa)
    return HasilCari("tidak_ditemukan", nomor_terbaik, kata, frasa)
