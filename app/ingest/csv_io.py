from __future__ import annotations

import csv
from pathlib import Path


def baca_csv(path: str | Path) -> list[dict[str, str]]:
    """Baca CSV UTF-8 (dengan/tanpa BOM). Baris yang seluruhnya kosong dilewati."""
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        pembaca = csv.DictReader(f)
        return [
            {(k or "").strip(): (v or "").strip() for k, v in baris.items()}
            for baris in pembaca
            if any((v or "").strip() for v in baris.values())
        ]
