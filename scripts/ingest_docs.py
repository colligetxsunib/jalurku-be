"""Ingest dokumen RAG: baca PDF/HTML dari data/dokumen/, potong, embed, simpan ke rag_chunks.

    uv run python -m scripts.ingest_docs --dry-run         # hanya chunking, tanpa API
    uv run python -m scripts.ingest_docs                   # semua dokumen terdaftar
    uv run python -m scripts.ingest_docs --dokumen snpmb-faq

Dokumen yang berkasnya belum ada di data/dokumen/ DILEWATI (bukan error); gagal hanya bila tidak ada satu pun berkas.
Prasyarat: dokumen_rag_metadata.csv sudah di-ingest (scripts.ingest) dan berkasnya diunduh manual ke
data/dokumen/<dokumen_id>.pdf|.html. Butuh GEMINI_API_KEY (kecuali --dry-run). Idempoten: chunk yang
tidak berubah tidak di-embed ulang.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_app_config, get_settings
from app.db.models import DokumenSumber
from app.db.session import make_engine
from app.llm.errors import LLMError
from app.llm.service import buat_client
from app.rag.chunking import ChunkTerlaluBesar
from app.rag.extract import BerkasTidakAda, TanpaTeks, cari_berkas
from app.rag.ingest import DokumenTidakTerdaftar, buat_chunk, ingest_dokumen


def main(argv: list[str] | None = None) -> int:
    settings, config = get_settings(), get_app_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dokumen", nargs="+", help="dokumen_id (default: semua yang terdaftar)")
    ap.add_argument("--dir", default=settings.dokumen_dir)
    ap.add_argument("--dry-run", action="store_true", help="hanya chunking, tanpa memanggil API")
    ap.add_argument("--database-url", default=settings.database_url)
    ap.add_argument(
        "--jeda-retry", type=float, default=5.0, help="detik, dikalikan nomor percobaan"
    )
    args = ap.parse_args(argv)

    if not args.dry_run and not settings.gemini_api_key:
        print(
            "GEMINI_API_KEY belum diisi (.env). Pakai --dry-run untuk mencoba chunking saja.",
            file=sys.stderr,
        )
        return 2

    engine = make_engine(args.database_url)
    klien = None if args.dry_run else buat_client(settings, config)
    gagal = 0
    dilewati = 0
    with Session(engine) as db:
        terdaftar = list(db.execute(select(DokumenSumber.id).order_by(DokumenSumber.id)).scalars())
        target = args.dokumen or terdaftar
        if not terdaftar:
            print(
                "Belum ada dokumen terdaftar. Jalankan: uv run python -m scripts.ingest --tipe dokumen",
                file=sys.stderr,
            )
            return 1
        for dokumen_id in target:
            try:
                if args.dry_run:
                    if dokumen_id not in terdaftar:
                        raise DokumenTidakTerdaftar(f"dokumen '{dokumen_id}' belum terdaftar")
                    chunks = buat_chunk(cari_berkas(args.dir, dokumen_id), config)
                    panjang = [len(c.teks) for c in chunks]
                    halaman = sorted({c.halaman for c in chunks if c.halaman is not None})
                    print(
                        f"[DRY]  {dokumen_id}: {len(chunks)} chunk, panjang {min(panjang)}-{max(panjang)} "
                        f"(rata-rata {sum(panjang) // len(panjang)}), halaman {len(halaman)}"
                    )
                else:
                    h = ingest_dokumen(
                        db, klien, config, dokumen_id, Path(args.dir), jeda_detik=args.jeda_retry
                    )
                    print(
                        f"[OK]   {dokumen_id}: {h.jumlah_chunk} chunk ({h.di_embed} di-embed, "
                        f"{h.tidak_berubah} tidak berubah, {h.dihapus} dihapus) dari {h.berkas}, "
                        f"{h.panggilan_embed} panggilan embedding"
                    )
            except BerkasTidakAda as exc:
                # Dokumen opsional (mis. snpmb-faq, halaman web): berkas belum diunduh = dilewati, bukan error.
                dilewati += 1
                print(f"[LEWATI] {dokumen_id}: {exc}")
            except (
                TanpaTeks,
                DokumenTidakTerdaftar,
                ChunkTerlaluBesar,
                ValueError,
            ) as exc:
                gagal += 1
                print(f"[GAGAL] {dokumen_id}: {exc}")
            except LLMError as exc:
                gagal += 1
                print(
                    f"[GAGAL] {dokumen_id}: embedding gagal ({type(exc).__name__}). Coba lagi nanti."
                )
    engine.dispose()
    if dilewati and dilewati == len(target):
        print(
            f"[GAGAL] tidak ada satu pun berkas dokumen ditemukan di {args.dir}.",
            file=sys.stderr,
        )
        return 1
    if dilewati:
        print(f"{dilewati} dokumen dilewati karena berkasnya belum ada (opsional).")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
