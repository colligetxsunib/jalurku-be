"""Deteksi pertanyaan bertipe keputusan dengan aturan kata kunci sederhana (FR-Q5). Murni, tanpa LLM.

Pertanyaan keputusan ("aku lolos nggak?", "apakah saya pasti lolos SNBP?") WAJIB dijawab dari hasil
mesin aturan. Pertanyaan tentang aturan umum ("berapa pilihan SNBP?") dijawab dari dokumen resmi (RAG).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence


def _kanon(teks: str) -> str:
    t = unicodedata.normalize("NFKC", teks).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def adalah_pertanyaan_eksplorasi(pertanyaan: str, pola: Sequence[str]) -> bool:
    """True bila pertanyaan bertema minat atau pilihan jurusan (dialihkan ke fitur eksplorasi)."""
    t = _kanon(pertanyaan)
    return any(re.search(p, t) for p in pola)


def adalah_pertanyaan_keputusan(
    pertanyaan: str, pola: Sequence[str], pengecualian: Sequence[str] = ()
) -> bool:
    """True bila ada pola keputusan yang cocok dan bukan kalimat bersyarat."""
    t = _kanon(pertanyaan)
    if any(re.search(rf"\b{re.escape(k)}\b", t) for k in pengecualian):
        return False
    return any(re.search(p, t) for p in pola)
