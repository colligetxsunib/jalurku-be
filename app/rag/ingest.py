"""Ingest dokumen ke `rag_chunks`: ekstrak -> chunk -> embed (RETRIEVAL_DOCUMENT) -> upsert.

- Idempoten: chunk yang teks, halaman, dan modelnya tidak berubah TIDAK di-embed ulang (hemat kuota).
- Semua embedding dihitung SEBELUM menulis ke DB; gagal di tengah jalan = tidak ada yang tersimpan.
- Vektor dari klien sudah dinormalisasi L2 (cosine = dot product).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.llm.client import LLMClient
from app.llm.errors import LLMGagal, LLMKuotaHabis, LLMTimeout
from app.rag.chunking import Chunk, potong_dokumen
from app.rag.extract import cari_berkas, ekstrak

log = logging.getLogger("jalurku.rag.ingest")


class DokumenTidakTerdaftar(LookupError):
    pass


@dataclass(frozen=True)
class HasilIngestDokumen:
    dokumen_id: str
    jumlah_chunk: int
    di_embed: int  # baru atau berubah
    tidak_berubah: int
    dihapus: int
    panggilan_embed: int
    berkas: str


def embed_dengan_retry(
    klien: LLMClient,
    teks: Sequence[str],
    *,
    task_type: str,
    retry: int,
    jeda_detik: float,
    tidur: Callable[[float], None] = time.sleep,
) -> list[list[float]]:
    """Ulangi saat kuota habis/timeout dengan jeda bertambah; error lain langsung naik."""
    for percobaan in range(retry + 1):
        try:
            return klien.embed(teks, task_type=task_type)
        except (LLMKuotaHabis, LLMTimeout) as exc:
            if percobaan == retry:
                raise
            tunggu = jeda_detik * (percobaan + 1)
            log.warning("embedding %s, ulangi dalam %.0f detik", type(exc).__name__, tunggu)
            tidur(tunggu)
    raise LLMGagal("tidak mencapai hasil embedding")  # pragma: no cover


def buat_chunk(path: Path, config: AppConfig) -> list[Chunk]:
    r = config.rag
    chunks = potong_dokumen(
        ekstrak(path),
        minimum=r.ukuran_chunk_min,
        maksimum=r.ukuran_chunk_maks,
        overlap=r.overlap_chunk,
        maks_token=r.maks_token_chunk,
    )
    if not chunks:
        raise ValueError(f"{path.name}: tidak ada chunk yang dihasilkan")
    return chunks


def ingest_dokumen(
    db: Session,
    klien: LLMClient,
    config: AppConfig,
    dokumen_id: str,
    direktori: str | Path,
    *,
    retry: int = 3,
    jeda_detik: float = 5.0,
    tidur: Callable[[float], None] = time.sleep,
) -> HasilIngestDokumen:
    dok = db.get(m.DokumenSumber, dokumen_id)
    if dok is None:
        raise DokumenTidakTerdaftar(
            f"dokumen '{dokumen_id}' belum terdaftar di dokumen_sumber (ingest dokumen_rag_metadata.csv dulu)"
        )
    path = cari_berkas(direktori, dokumen_id)
    chunks = buat_chunk(path, config)

    model = config.embedding.model
    dimensi = config.embedding.dimensi
    ada = {
        c.urutan: (c.teks, c.halaman, c.embedding_model)
        for c in db.execute(select(m.RagChunk).where(m.RagChunk.dokumen_id == dokumen_id)).scalars()
    }
    perlu = [c for c in chunks if ada.get(c.urutan) != (c.teks, c.halaman, model)]

    vektor: dict[int, list[float]] = {}
    batch = config.rag.ukuran_batch_embedding
    panggilan = 0
    for i in range(0, len(perlu), batch):
        bagian = perlu[i : i + batch]
        hasil = embed_dengan_retry(
            klien,
            [c.teks for c in bagian],
            task_type="RETRIEVAL_DOCUMENT",
            retry=retry,
            jeda_detik=jeda_detik,
            tidur=tidur,
        )
        panggilan += 1
        if len(hasil) != len(bagian) or any(len(v) != dimensi for v in hasil):
            raise LLMGagal(f"embedding tidak sesuai: harus {dimensi} dimensi per chunk")
        for c, v in zip(bagian, hasil, strict=True):
            vektor[c.urutan] = v

    try:
        if perlu:
            baris = [
                {
                    "dokumen_id": dokumen_id,
                    "urutan": c.urutan,
                    "teks": c.teks,
                    "embedding": vektor[c.urutan],
                    "embedding_model": model,
                    "halaman": c.halaman,
                    "sumber_url": dok.url,
                    "tahun_siklus": dok.tahun_siklus,
                }
                for c in perlu
            ]
            stmt = pg_insert(m.RagChunk).values(baris)
            stmt = stmt.on_conflict_do_update(
                index_elements=["dokumen_id", "urutan"],
                set_={
                    k: stmt.excluded[k]
                    for k in (
                        "teks",
                        "embedding",
                        "embedding_model",
                        "halaman",
                        "sumber_url",
                        "tahun_siklus",
                    )
                },
            )
            db.execute(stmt)
        hasil_hapus = db.execute(
            delete(m.RagChunk).where(
                m.RagChunk.dokumen_id == dokumen_id, m.RagChunk.urutan >= len(chunks)
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return HasilIngestDokumen(
        dokumen_id=dokumen_id,
        jumlah_chunk=len(chunks),
        di_embed=len(perlu),
        tidak_berubah=len(chunks) - len(perlu),
        dihapus=hasil_hapus.rowcount or 0,
        panggilan_embed=panggilan,
        berkas=path.name,
    )
