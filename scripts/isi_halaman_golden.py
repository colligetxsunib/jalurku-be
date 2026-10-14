"""Isi kolom `halaman` golden set RAG dengan mencari teks jawaban di PDF sumber.

    python -m scripts.isi_halaman_golden             # simulasi: hanya laporan, berkas tidak diubah
    python -m scripts.isi_halaman_golden --tulis     # tulis hasil ke golden_set.csv

Per pertanyaan yang punya `sumber_url`: PDF dicari lewat dokumen_rag_metadata.csv ke
data/dokumen/<dokumen_id>.pdf, teks jawaban dicocokkan ke tiap halaman (lihat
app/evaluasi/cari_halaman.py), lalu kolom `status_halaman` diisi:

    ditemukan         halaman cukup yakin, kolom `halaman` DIISI
    perkiraan         ada kandidat tetapi kurang yakin, `halaman` TIDAK diisi (cek manual);
                      dengan --terima-perkiraan kandidat diisi dan statusnya jadi perkiraan_diterima
    tidak_ditemukan   tidak ada halaman yang cukup mirip, perlu dicek manusia
    dokumen_tidak_ada PDF belum diunduh ke data/dokumen/
    sudah_terisi      kolom `halaman` sudah diisi manusia, tidak disentuh (kecuali --timpa)

Pertanyaan tanpa sumber_url (di luar cakupan) tidak diproses. Kolom `halaman` yang sudah terisi tidak
pernah ditimpa tanpa --timpa. Skrip ini tidak memanggil API apa pun.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import unquote

from app.core.config import ROOT_DIR, get_settings
from app.evaluasi import cari_halaman, golden
from app.rag.extract import BerkasTidakAda, TanpaTeks, cari_berkas, ekstrak

KOLOM_STATUS = "status_halaman"
METADATA_DEFAULT = ROOT_DIR / "data" / "seed" / "dokumen_rag_metadata.csv"

MuatHalaman = Callable[[str], Sequence[tuple[int | None, str]] | None]


def _norm(url: str) -> str:
    return unquote(url).strip().rstrip("/").lower()


def peta_url_ke_dokumen(metadata: Path) -> dict[str, str]:
    with metadata.open(encoding="utf-8-sig", newline="") as f:
        return {_norm(r["url"]): r["dokumen_id"] for r in csv.DictReader(f) if r.get("url")}


def proses_baris(
    baris: list[dict[str, str]],
    url_ke_dokumen: dict[str, str],
    muat_halaman: MuatHalaman,
    *,
    timpa: bool = False,
    terima_perkiraan: bool = False,
) -> list[dict[str, str]]:
    """Kembalikan salinan baris dengan `halaman` dan `status_halaman` diperbarui."""
    cache: dict[str, Sequence[tuple[int | None, str]] | None] = {}
    hasil: list[dict[str, str]] = []
    for b in baris:
        b = dict(b)
        b.setdefault(KOLOM_STATUS, "")
        url = (b.get("sumber_url") or "").strip()
        if not url:
            hasil.append(b)  # di luar cakupan: tidak ada sumber untuk dicari
            continue
        if (b.get("halaman") or "").strip() and not timpa:
            b[KOLOM_STATUS] = "sudah_terisi"
            hasil.append(b)
            continue
        dokumen_id = url_ke_dokumen.get(_norm(url))
        if dokumen_id is None:
            b[KOLOM_STATUS] = "dokumen_tidak_terdaftar"
            hasil.append(b)
            continue
        if dokumen_id not in cache:
            cache[dokumen_id] = muat_halaman(dokumen_id)
        halaman = cache[dokumen_id]
        if halaman is None:
            b[KOLOM_STATUS] = "dokumen_tidak_ada"
            hasil.append(b)
            continue
        r = cari_halaman.cari(b["jawaban_benar"], halaman)
        b[KOLOM_STATUS] = r.catatan()
        if r.status == "ditemukan" and r.halaman is not None:
            b["halaman"] = str(r.halaman)
        elif r.status == "perkiraan" and terima_perkiraan and r.halaman is not None:
            b["halaman"] = str(r.halaman)
            b[KOLOM_STATUS] = "perkiraan_diterima " + r.catatan().removeprefix("perkiraan ")
        elif timpa:
            b["halaman"] = ""
        hasil.append(b)
    return hasil


def muat_dari_direktori(direktori: Path) -> MuatHalaman:
    def muat(dokumen_id: str):
        try:
            return ekstrak(cari_berkas(direktori, dokumen_id))
        except (BerkasTidakAda, TanpaTeks):
            return None

    return muat


def _gaya_baris(path: Path) -> str:
    return "\r\n" if b"\r\n" in path.read_bytes() else "\n"


def tulis_csv(path: Path, kolom: list[str], baris: list[dict[str, str]], akhir_baris: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=kolom, lineterminator=akhir_baris, extrasaction="ignore")
        w.writeheader()
        w.writerows(baris)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--golden", default=str(golden.GOLDEN_RAG_CSV))
    ap.add_argument("--metadata", default=str(METADATA_DEFAULT))
    ap.add_argument("--dokumen-dir", default=get_settings().dokumen_dir)
    ap.add_argument("--tulis", action="store_true", help="tulis hasil ke berkas golden")
    ap.add_argument("--timpa", action="store_true", help="timpa halaman yang sudah terisi")
    ap.add_argument(
        "--terima-perkiraan",
        action="store_true",
        help="isi halaman juga untuk status 'perkiraan' (jalankan setelah Anda memeriksa laporannya)",
    )
    a = ap.parse_args(argv)

    path = Path(a.golden)
    with path.open(encoding="utf-8-sig", newline="") as f:
        pembaca = csv.DictReader(f)
        kolom = list(pembaca.fieldnames or [])
        baris = list(pembaca)
    if KOLOM_STATUS not in kolom:
        kolom.append(KOLOM_STATUS)

    hasil = proses_baris(
        baris,
        peta_url_ke_dokumen(Path(a.metadata)),
        muat_dari_direktori(Path(a.dokumen_dir)),
        timpa=a.timpa,
        terima_perkiraan=a.terima_perkiraan,
    )

    ringkas: dict[str, int] = {}
    for no, (lama, baru) in enumerate(zip(baris, hasil, strict=True), start=1):
        if not (lama.get("sumber_url") or "").strip():
            continue
        status = baru[KOLOM_STATUS].split(" ")[0]
        ringkas[status] = ringkas.get(status, 0) + 1
        tanda = {"ditemukan": "OK", "perkiraan": "CEK", "sudah_terisi": "--"}.get(status, "TIDAK")
        print(f"[{tanda:5}] {no:2}. hal. {baru['halaman'] or '-':>3}  {baru[KOLOM_STATUS]}")
        print(f"          {baru['pertanyaan'][:90]}")
    print("\nRingkasan: " + ", ".join(f"{k}={v}" for k, v in sorted(ringkas.items())))

    if a.tulis:
        tulis_csv(path, kolom, hasil, _gaya_baris(path))
        print(f"Ditulis ke {path}")
    else:
        print("Simulasi saja. Tambahkan --tulis untuk menyimpan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
