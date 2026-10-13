"""Retrieve: pencarian vektor eksak (cosine) di pgvector, tanpa indeks ANN (cukup untuk ratusan-ribuan chunk)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m


@dataclass(frozen=True)
class HasilCari:
    chunk_id: int
    dokumen_id: str
    judul: str
    url: str
    halaman: int | None
    teks: str
    tahun_siklus: int
    skor: float  # kemiripan cosine, 1.0 = identik


def cari(
    db: Session, vektor: Sequence[float], *, top_k: int, embedding_model: str
) -> list[HasilCari]:
    """Top-k chunk paling mirip. Hanya chunk dengan `embedding_model` yang sama (tidak pernah dicampur)."""
    jarak = m.RagChunk.embedding.cosine_distance(list(vektor)).label("jarak")
    kueri = (
        select(
            m.RagChunk.id,
            m.RagChunk.dokumen_id,
            m.DokumenSumber.judul,
            m.RagChunk.sumber_url,
            m.RagChunk.halaman,
            m.RagChunk.teks,
            m.RagChunk.tahun_siklus,
            jarak,
        )
        .join(m.DokumenSumber, m.DokumenSumber.id == m.RagChunk.dokumen_id)
        .where(m.RagChunk.embedding_model == embedding_model)
        .order_by(jarak, m.RagChunk.id)
        .limit(top_k)
    )
    return [
        HasilCari(cid, did, judul, url, hal, teks, tahun, 1.0 - float(j))
        for cid, did, judul, url, hal, teks, tahun, j in db.execute(kueri)
    ]


def di_atas_ambang(hasil: Sequence[HasilCari], ambang: float) -> list[HasilCari]:
    return [h for h in hasil if h.skor >= ambang]
