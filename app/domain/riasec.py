"""Penilaian tes minat RIASEC: fungsi murni dan deterministik, tanpa DB dan tanpa LLM (PRD 8.5).

Model Holland/RIASEC memetakan minat ke enam dimensi: realistis (R), investigatif (I),
artistik (A), sosial (S), enterprising (E), konvensional (C). Item diadaptasi dari O*NET
Interest Profiler (U.S. Department of Labor, domain publik) ke bahasa Indonesia dan konteks
siswa SMA; lihat docs/riset-riasec.md.

Alur skoring:
1. Siswa menilai tiap aktivitas pada skala Likert (mis. 0..4: sangat tidak suka .. sangat suka).
2. Skor mentah per dimensi = jumlah jawaban item milik dimensi itu.
3. Skor dinormalisasi 0..1 (dibagi skor maksimum dimensi) → vektor `minat` yang disimpan di
   `profiles.minat` dan dikonsumsi `/explore` (app.domain.match.kemiripan_cosine).
4. Holland code = tiga dimensi dengan skor tertinggi, urut menurun (mis. "ICR").

Vektor keluaran memakai nama dimensi config (`minat.dimensi`), bukan huruf RIASEC, agar langsung
cocok dengan pipeline eksplorasi yang sudah ada. Penjelasan hasil (opsional, oleh LLM) dibangun
di luar modul ini; fungsi di sini hanya menyediakan angka deterministik.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemRiasec:
    """Satu pernyataan aktivitas. `id` stabil (dipakai sebagai kunci jawaban), `dimensi` ∈ minat.dimensi."""

    id: str
    dimensi: str
    teks: str


@dataclass(frozen=True)
class SkalaLikert:
    """Rentang nilai jawaban yang diterima, inklusif di kedua ujung (mis. 0..4)."""

    min: int
    maks: int

    @property
    def rentang(self) -> range:
        return range(self.min, self.maks + 1)


@dataclass(frozen=True)
class HasilRiasec:
    """Keluaran deterministik satu kali tes."""

    skor_mentah: dict[str, int]  # dimensi -> jumlah jawaban (satuan skala Likert)
    skor_norm: dict[str, float]  # dimensi -> 0..1 (vektor minat untuk /explore)
    holland_code: str  # 3 huruf dimensi tertinggi, mis. "ICR"
    dimensi_teratas: list[str]  # nama dimensi penuh, urut menurun
    jumlah_item: dict[str, int]  # dimensi -> banyak item (untuk transparansi)
    terjawab: int  # banyak item yang dijawab
    total_item: int  # banyak item instrumen


# Pemetaan nama dimensi config → huruf Holland untuk membentuk kode (mis. "ICR").
# Hanya untuk tampilan; perhitungan tetap memakai nama dimensi penuh.
_HURUF_HOLLAND: dict[str, str] = {
    "realistis": "R",
    "investigatif": "I",
    "artistik": "A",
    "sosial": "S",
    "enterprising": "E",
    "konvensional": "C",
}


def validasi_instrumen(
    item: Sequence[ItemRiasec], dimensi: Sequence[str]
) -> list[str]:
    """Periksa konsistensi bank item terhadap dimensi config. Mengembalikan daftar pesan galat.

    Dipakai saat start (fail-fast lewat validator config) agar instrumen cacat tidak dipakai.
    """
    galat: list[str] = []
    dikenal = set(dimensi)

    ids = [i.id for i in item]
    duplikat = sorted({x for x in ids if ids.count(x) > 1})
    if duplikat:
        galat.append(f"id item duplikat: {', '.join(duplikat)}")

    asing = sorted({i.dimensi for i in item} - dikenal)
    if asing:
        galat.append(f"item memakai dimensi tak dikenal: {', '.join(asing)}")

    kosong = sorted(d for d in dikenal if not any(i.dimensi == d for i in item))
    if kosong:
        galat.append(f"dimensi tanpa item: {', '.join(kosong)}")

    return galat


def hitung(
    jawaban: Mapping[str, int],
    item: Sequence[ItemRiasec],
    skala: SkalaLikert,
    dimensi: Sequence[str],
) -> HasilRiasec:
    """Hitung vektor minat dari jawaban. Deterministik; item yang tidak dijawab dilewati.

    `jawaban` memetakan id item → nilai skala. Normalisasi memakai hanya item yang dijawab per
    dimensi, sehingga tes parsial tetap menghasilkan vektor yang masuk akal (0..1).
    """
    per_dimensi: dict[str, list[ItemRiasec]] = {d: [] for d in dimensi}
    for it in item:
        if it.dimensi in per_dimensi:
            per_dimensi[it.dimensi].append(it)

    skor_mentah: dict[str, int] = {}
    skor_norm: dict[str, float] = {}
    jumlah_item: dict[str, int] = {}
    terjawab = 0

    for d in dimensi:
        item_d = per_dimensi[d]
        jumlah_item[d] = len(item_d)
        dijawab = [jawaban[it.id] for it in item_d if it.id in jawaban]
        terjawab += len(dijawab)
        total = sum(v - skala.min for v in dijawab)  # geser agar min skala = 0
        skor_mentah[d] = total
        maks = len(dijawab) * (skala.maks - skala.min)
        skor_norm[d] = round(total / maks, 4) if maks > 0 else 0.0

    urut = sorted(dimensi, key=lambda d: (-skor_norm[d], d))
    holland = "".join(_HURUF_HOLLAND.get(d, d[:1].upper()) for d in urut[:3])

    return HasilRiasec(
        skor_mentah=skor_mentah,
        skor_norm=skor_norm,
        holland_code=holland,
        dimensi_teratas=urut[:3],
        jumlah_item=jumlah_item,
        terjawab=terjawab,
        total_item=len(item),
    )


def jawaban_di_luar_skala(jawaban: Mapping[str, int], skala: SkalaLikert) -> list[str]:
    """Id item yang nilainya di luar rentang skala (untuk pesan validasi 422)."""
    return sorted(k for k, v in jawaban.items() if v not in skala.rentang)


def id_tak_dikenal(jawaban: Mapping[str, int], item: Sequence[ItemRiasec]) -> list[str]:
    """Id jawaban yang tidak ada di instrumen (untuk pesan validasi 422)."""
    dikenal = {it.id for it in item}
    return sorted(k for k in jawaban if k not in dikenal)
