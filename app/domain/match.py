"""Skor kecocokan eksplorasi jurusan (PRD 8.3): fungsi murni dan deterministik, tanpa LLM.

kecocokan = bobot_minat * kemiripan_minat + bobot_nilai * kesesuaian_nilai

- kemiripan_minat: cosine antara vektor minat siswa dan vektor minat rumpun (keduanya >= 0, jadi 0..1).
- kesesuaian_nilai: rata-rata tertimbang nilai rapor pada mapel relevan, dibagi 100. Mapel yang belum
  diisi dikeluarkan dari perhitungan dan ditandai.
- Komponen yang tidak dapat dihitung dikeluarkan dan bobot sisanya dinormalisasi.
Hasil hanya menyatakan kemiripan, bukan peluang diterima.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import sqrt


def kemiripan_cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float | None:
    """Cosine dua vektor non-negatif berkunci dimensi. None bila salah satu vektor nol."""
    na = sqrt(sum(v * v for v in a.values()))
    nb = sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return None
    dot = sum(v * b[d] for d, v in a.items() if d in b)
    return min(1.0, max(0.0, dot / (na * nb)))


def dimensi_teratas(
    minat_siswa: Mapping[str, float], profil_rumpun: Mapping[str, float], n: int = 2
) -> list[str]:
    """Dimensi dengan sumbangan terbesar ke kemiripan (minat siswa x bobot rumpun), urut stabil."""
    sumbangan = {d: v * profil_rumpun[d] for d, v in minat_siswa.items() if d in profil_rumpun}
    urut = sorted((d for d, s in sumbangan.items() if s > 0), key=lambda d: (-sumbangan[d], d))
    return urut[:n]


@dataclass(frozen=True)
class SkorNilai:
    skor: float | None  # 0..1, None bila tidak ada mapel relevan yang terisi
    dipakai: dict[str, float]  # mapel -> rata-rata nilai (0..100) yang ikut dihitung
    kosong: list[str]  # mapel relevan yang belum diisi (ditandai, tidak dihitung)


def kesesuaian_nilai(
    rata_mapel: Mapping[str, float], bobot_mapel: Mapping[str, float]
) -> SkorNilai:
    dipakai = {m: rata_mapel[m] for m in sorted(bobot_mapel) if m in rata_mapel}
    kosong = sorted(m for m in bobot_mapel if m not in rata_mapel)
    if not dipakai:
        return SkorNilai(None, {}, kosong)
    total = sum(bobot_mapel[m] for m in dipakai)
    skor = sum(bobot_mapel[m] * dipakai[m] for m in dipakai) / total / 100
    return SkorNilai(min(1.0, max(0.0, skor)), dipakai, kosong)


def gabung_kecocokan(
    minat: float | None, nilai: float | None, bobot_minat: float, bobot_nilai: float
) -> tuple[float | None, dict[str, float]]:
    """(skor 0..1, bobot efektif). Komponen None atau berbobot 0 dikeluarkan lalu bobot dinormalisasi."""
    bagian = [
        (nama, skor, bobot)
        for nama, skor, bobot in (("minat", minat, bobot_minat), ("nilai", nilai, bobot_nilai))
        if skor is not None and bobot > 0
    ]
    if not bagian:
        return None, {}
    total = sum(b for _, _, b in bagian)
    return (
        sum(s * b for _, s, b in bagian) / total,
        {nama: b / total for nama, _, b in bagian},
    )


def mapel_terbaik(
    dipakai: Mapping[str, float], bobot: Mapping[str, float]
) -> tuple[str, float] | None:
    """Mapel relevan dengan sumbangan terbesar (bobot x nilai) untuk kalimat alasan."""
    if not dipakai:
        return None
    nama = min(dipakai, key=lambda m: (-(bobot[m] * dipakai[m]), m))
    return nama, dipakai[nama]


def _sebut(daftar: Sequence[str]) -> str:
    if len(daftar) <= 1:
        return "".join(daftar)
    return ", ".join(daftar[:-1]) + " dan " + daftar[-1]


def alasan_template(
    *,
    dimensi: Sequence[str],
    terbaik: tuple[str, float] | None,
    mapel_kosong: Sequence[str],
    minat_diisi: bool,
) -> str:
    """Penjelasan dari template (FR-E2): "Cocok karena minatmu pada {dimensi} serta nilai {mapel} {nilai}"."""
    bagian: list[str] = []
    if dimensi:
        bagian.append(f"minatmu pada {_sebut(list(dimensi))}")
    if terbaik:
        bagian.append(f"nilai {terbaik[0].replace('_', ' ')} {terbaik[1]:.0f}")
    kalimat = ("Cocok karena " + " serta ".join(bagian) + ".") if bagian else "Kecocokan rendah."
    catatan: list[str] = []
    if not minat_diisi:
        catatan.append("Minat belum diisi, jadi skor hanya dari nilai.")
    if mapel_kosong:
        catatan.append(
            "Nilai belum diisi untuk mapel relevan: "
            + ", ".join(m.replace("_", " ") for m in mapel_kosong)
            + "."
        )
    return " ".join([kalimat, *catatan])
