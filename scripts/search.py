"""Uji retrieval dari terminal: top-k chunk untuk sebuah pertanyaan (butuh GEMINI_API_KEY + chunk terisi).

uv run python -m scripts.search "Berapa jumlah pilihan prodi di SNBP?"
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.core.config import get_app_config, get_settings
from app.db.session import make_engine
from app.llm.pii import saring_pii
from app.llm.service import LLMService, buat_client
from app.rag.retrieve import cari


def main(argv: list[str] | None = None) -> int:
    settings, config = get_settings(), get_app_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("pertanyaan")
    ap.add_argument("--top-k", type=int, default=config.rag.top_k)
    args = ap.parse_args(argv)

    if not settings.gemini_api_key:
        print("GEMINI_API_KEY belum diisi (.env).", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url)
    svc = LLMService(buat_client(settings, config), config)
    with Session(engine) as db:
        emb = svc.embed_pertanyaan(db, saring_pii(args.pertanyaan).teks)
        if emb.vektor is None:
            print(f"Embedding gagal ({emb.alasan}).", file=sys.stderr)
            return 1
        hasil = cari(db, emb.vektor, top_k=args.top_k, embedding_model=config.embedding.model)
    print(
        f"Ambang LLM: {config.rag.ambang_skor}. Skor tertinggi: {hasil[0].skor:.3f}"
        if hasil
        else "Tidak ada chunk."
    )
    for h in hasil:
        tanda = "OK " if h.skor >= config.rag.ambang_skor else "   "
        hal = f" hal. {h.halaman}" if h.halaman is not None else ""
        print(
            f"{tanda}{h.skor:.3f}  {h.judul}{hal}\n       {h.teks[:200].replace(chr(10), ' ')}..."
        )
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
