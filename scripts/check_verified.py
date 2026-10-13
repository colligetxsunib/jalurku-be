"""Periksa kesiapan verifikasi data sebelum rekam video dan submit.

    python -m scripts.check_verified               # ringkasan
    python -m scripts.check_verified --detail      # daftar baris yang belum terverifikasi
    python -m scripts.check_verified --ketat       # katalog (ptn, prodi, ...) ikut dihitung gagal

Yang diperiksa:
- tabel kritis di DB (rules_jalur, ketentuan, acuan_skor): wajib terverifikasi, inilah yang dijaga
  REQUIRE_VERIFIED=true saat start;
- katalog (ptn, prodi, prodi_jalur, dokumen_sumber): peringatan, gagal hanya dengan --ketat;
- persona demo dan kasus golden gate: `hasil_terverifikasi` / `terakhir_diverifikasi` harus diisi
  manusia setelah mencocokkan dengan sumber resmi;
- kecukupan golden set RAG terhadap syarat PRD.

Skrip ini hanya MELAPORKAN. Ia tidak pernah mengisi tanggal verifikasi. Kode keluar 1 bila ada yang
wajib tetapi belum terverifikasi.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import make_engine
from app.db.verifikasi import (
    TABEL_KATALOG,
    TABEL_KRITIS,
    cari_belum_terverifikasi,
    hitung_per_tabel,
)
from app.evaluasi import golden
from app.services import persona as modul_persona

MAKS_DETAIL = 25


def _baris_tabel(nama: str, belum: int, total: int) -> str:
    status = "OK     " if belum == 0 else "BELUM  "
    return f"   [{status}] {nama:<15} {total - belum}/{total} terverifikasi"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--detail", action="store_true", help="tampilkan baris yang belum terverifikasi"
    )
    ap.add_argument("--ketat", action="store_true", help="katalog yang belum terverifikasi = gagal")
    ap.add_argument("--database-url", default=None)
    a = ap.parse_args(argv)

    settings = get_settings()
    gagal = False

    print(f"REQUIRE_VERIFIED saat ini: {'true' if settings.require_verified else 'false'}")
    engine = make_engine(a.database_url or settings.database_url)
    with Session(engine) as db:
        hitung = hitung_per_tabel(db, lengkap=True)
        temuan = cari_belum_terverifikasi(db, lengkap=True)
    engine.dispose()

    print("\n1. Tabel kritis (dijaga REQUIRE_VERIFIED saat start)")
    for t in TABEL_KRITIS:
        belum, total = hitung[t]
        print(_baris_tabel(t, belum, total))
        gagal |= belum > 0
        if total == 0 and t != "acuan_skor":
            print(f"      {t} kosong: jalankan ingest dulu (python -m scripts.ingest)")
        if total == 0 and t == "acuan_skor":
            print("      acuan_skor kosong (belum ada acuan resmi): penilaian memakai keketatan")

    print("\n2. Katalog" + (" (ketat)" if a.ketat else " (peringatan)"))
    for t in TABEL_KATALOG:
        belum, total = hitung[t]
        print(_baris_tabel(t, belum, total))
        if a.ketat:
            gagal |= belum > 0

    if a.detail and temuan:
        print("\n   Baris belum terverifikasi:")
        for t in temuan[:MAKS_DETAIL]:
            print(f"   - {t.tabel}/{t.kunci}: {t.alasan}")
        if len(temuan) > MAKS_DETAIL:
            print(f"   ... dan {len(temuan) - MAKS_DETAIL} lainnya")

    print("\n3. Persona demo (hasil terverifikasi manusia)")
    for p in modul_persona.muat_semua():
        h = p.harapan
        ok = h.hasil_terverifikasi
        gagal |= not ok
        oleh = f" oleh {h.diverifikasi_oleh} pada {h.terakhir_diverifikasi}" if ok else ""
        print(f"   [{'OK     ' if ok else 'BELUM  '}] {p.id}{oleh}")

    print("\n4. Kasus golden gate")
    kasus = golden.muat_kasus_gate()
    belum_kasus = [k.id for k in kasus if not k.terverifikasi]
    print(
        f"   [{'OK     ' if not belum_kasus else 'BELUM  '}] {len(kasus) - len(belum_kasus)}/{len(kasus)} terverifikasi"
    )
    gagal |= bool(belum_kasus)
    if a.detail and belum_kasus:
        print("   Belum: " + ", ".join(belum_kasus))

    print("\n5. Golden set RAG (data/seed/golden_set_draft.csv)")
    kurang = golden.periksa_kecukupan(golden.muat_soal_rag())
    for k in kurang:
        print(f"   [KURANG ] {k}")
    if not kurang:
        print("   [OK     ] memenuhi syarat minimal PRD")

    print(
        "\n"
        + (
            "SIAP: semua yang wajib sudah terverifikasi."
            if not gagal
            else "BELUM SIAP: ada yang wajib tetapi belum terverifikasi manusia."
        )
    )
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
