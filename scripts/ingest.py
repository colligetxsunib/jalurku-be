"""Muat data seed (CSV) ke database lewat layanan ingest yang sama dengan POST /admin/ingest.

    uv run python -m scripts.ingest                        # data/seed, semua tipe
    uv run python -m scripts.ingest --tipe katalog acuan   # sebagian
    uv run python -m scripts.ingest --require-verified     # tolak data tanpa terakhir_diverifikasi

Satu tipe = satu transaksi: ada satu baris salah, tipe itu tidak tersimpan sama sekali.
Idempoten: boleh dijalankan ulang (upsert).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import make_engine
from app.ingest.service import TIPE_VALID, URUTAN_SEED, ingest_direktori

MAKS_ERROR_DITAMPILKAN = 40


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dir", default=settings.seed_dir, help="folder CSV (default: data/seed)")
    ap.add_argument("--tipe", nargs="+", choices=TIPE_VALID, help=f"urutan tetap: {URUTAN_SEED}")
    ap.add_argument(
        "--require-verified",
        action="store_true",
        help="tolak baris tanpa terakhir_diverifikasi (juga aktif bila REQUIRE_VERIFIED=true)",
    )
    ap.add_argument("--database-url", default=settings.database_url)
    args = ap.parse_args(argv)

    engine = make_engine(args.database_url)
    gagal = False
    with Session(engine) as db:
        for hasil in ingest_direktori(
            db,
            args.dir,
            require_verified=args.require_verified or settings.require_verified,
            tipe=args.tipe,
        ):
            if hasil.ok:
                rinci = ", ".join(f"{k}={v}" for k, v in hasil.ringkasan.items())
                print(f"[OK]    {hasil.tipe:<10} diterima={hasil.diterima} ({rinci})")
                continue
            gagal = True
            print(f"[DITOLAK] {hasil.tipe:<8} {len(hasil.error)} error, tidak ada data tersimpan:")
            for e in hasil.error[:MAKS_ERROR_DITAMPILKAN]:
                print(f"    {e.sumber} baris {e.baris}: {e.pesan}")
            if len(hasil.error) > MAKS_ERROR_DITAMPILKAN:
                print(f"    ... dan {len(hasil.error) - MAKS_ERROR_DITAMPILKAN} error lain")
    engine.dispose()
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
