"""Jalankan gate untuk satu persona memakai rule_gate.csv dan config_ketentuan.csv asli (tanpa DB).

uv run python -m scripts.try_gate config/personas/budi.json SNBT
uv run python -m scripts.try_gate config/personas/dimas.json SNBP --prodi ui-teknik-industri
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.core.config import ROOT_DIR
from app.domain.fields import Target
from app.domain.gate import evaluasi_gate
from app.domain.ketentuan import Ketentuan
from app.ingest.csv_io import baca_csv
from app.ingest.rules import rules_dari_baris


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("persona", help="berkas persona JSON")
    ap.add_argument("jalur", choices=["SNBP", "SNBT"])
    ap.add_argument("--prodi", help="prodi_id untuk syarat per-target")
    ap.add_argument("--seed-dir", default=str(ROOT_DIR / "data" / "seed"))
    args = ap.parse_args(argv)

    persona = json.loads(Path(args.persona).read_text(encoding="utf-8"))
    seed = Path(args.seed_dir)
    rules_list, galat = rules_dari_baris(baca_csv(seed / "rule_gate.csv"))
    if galat:
        for g in galat:
            print(f"rule_gate baris {g.baris}: {g.pesan}", file=sys.stderr)
        return 1
    ketentuan = Ketentuan.dari_baris(baca_csv(seed / "config_ketentuan.csv"))
    rules = next(r for r in rules_list if r.jalur == args.jalur)

    target = Target(args.prodi, args.prodi) if args.prodi else None
    hasil = evaluasi_gate(rules, persona["profil"], ketentuan, target)

    print(f"{persona['nama']} | {args.jalur} {rules.tahun_siklus} | gate: {hasil.status.upper()}")
    for s in hasil.syarat:
        print(f"  [{s.status:>13}] {s.id}" + (f"  ({s.alasan})" if s.alasan else ""))
    if hasil.data_kurang:
        print("Data yang perlu dilengkapi:")
        for d in hasil.data_kurang:
            print(f"  - {d.field}: {d.pertanyaan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
