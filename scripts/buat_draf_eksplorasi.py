"""Buat DRAF data eksplorasi di data/draft/ (tag_minat RIASEC, mapel_penentu, contoh profesi).

Draf ini diturunkan mekanis dari klasifikasi awal tiap rumpun di config/app.yaml (bagian `explore`),
BUKAN dari sumber resmi, dan sama untuk semua prodi dalam satu rumpun. Gunanya memberi tim data
berkas awal yang bisa disunting per prodi. Setiap baris berlabel "draf, belum terverifikasi"; berkas
tidak memuat terakhir_diverifikasi dan tidak pernah menyentuh CSV utama di data/seed/.

    uv run python -m scripts.buat_draf_eksplorasi            # tulis data/draft/
    uv run python -m scripts.buat_draf_eksplorasi --cek      # gagal bila berkas draf tidak sama dengan hasil
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from app.core.config import ROOT_DIR, Settings, load_app_config
from app.services.draf_eksplorasi import LABEL_DRAF, NAMA_PRODI, NAMA_PROFESI

SEED_PRODI = ROOT_DIR / "data" / "seed" / "prodi.csv"
MIN_BOBOT_MINAT = 0.5  # dimensi rumpun dengan bobot >= ini menjadi tag_minat
MIN_BOBOT_MAPEL = 0.8  # mapel rumpun dengan bobot >= ini menjadi mapel_penentu
CATATAN_PRODI = (
    "diturunkan dari klasifikasi rumpun di config/app.yaml; belum disesuaikan per prodi, "
    "belum diverifikasi tim data"
)


def _csv(kolom: list[str], baris: list[dict[str, str]]) -> str:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=kolom, lineterminator="\n")
    w.writeheader()
    w.writerows(baris)
    return buf.getvalue()


def bangun() -> dict[str, str]:
    cfg = load_app_config(Settings(_env_file=None).app_config_path)
    with SEED_PRODI.open(encoding="utf-8-sig", newline="") as f:
        prodi = list(csv.DictReader(f))

    baris_prodi: list[dict[str, str]] = []
    for p in prodi:
        r = cfg.explore.rumpun.get(p["rumpun"])
        tag = sorted(
            (d for d, b in (r.minat if r else {}).items() if b >= MIN_BOBOT_MINAT),
            key=lambda d: (-r.minat[d], d),
        )
        mapel = sorted(
            (m for m, b in (r.mapel if r else {}).items() if b >= MIN_BOBOT_MAPEL),
            key=lambda m: (-r.mapel[m], m),
        )
        baris_prodi.append(
            {
                "prodi_id": p["prodi_id"],
                "rumpun": p["rumpun"],
                "tag_minat": "|".join(tag),
                "mapel_penentu": "|".join(mapel),
                "status": LABEL_DRAF,
                "catatan": CATATAN_PRODI if r else "rumpun tanpa klasifikasi awal; dikosongkan",
            }
        )

    baris_profesi = [
        {"rumpun": rumpun, "nama": nama, "deskripsi": "", "status": LABEL_DRAF}
        for rumpun, r in sorted(cfg.explore.rumpun.items())
        for nama in r.profesi
    ]
    return {
        NAMA_PRODI: _csv(
            ["prodi_id", "rumpun", "tag_minat", "mapel_penentu", "status", "catatan"], baris_prodi
        ),
        NAMA_PROFESI: _csv(["rumpun", "nama", "deskripsi", "status"], baris_profesi),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT_DIR / "data" / "draft")
    ap.add_argument("--cek", action="store_true", help="hanya periksa, jangan menulis")
    args = ap.parse_args(argv)

    hasil = bangun()
    if args.cek:
        usang = [
            n
            for n, isi in hasil.items()
            if not (args.out / n).is_file()
            or (args.out / n).read_text(encoding="utf-8-sig").replace("\r\n", "\n") != isi
        ]
        for n in usang:
            print(f"[USANG] {n}", file=sys.stderr)
        return 1 if usang else 0

    args.out.mkdir(parents=True, exist_ok=True)
    for nama, isi in hasil.items():
        (args.out / nama).write_text(isi, encoding="utf-8", newline="\n")
        print(f"[OK] {args.out / nama} ({isi.count(chr(10)) - 1} baris)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
