"""Jalankan golden set: akurasi gate, kesesuaian persona, dan (opsional) kualitas RAG.

    python -m scripts.run_golden_set                 # gate + persona (tanpa API Gemini)
    python -m scripts.run_golden_set --rag           # + RAG; butuh GEMINI_API_KEY dan dokumen ter-ingest
    python -m scripts.run_golden_set --hanya rag --laporan reports

Berjalan di dalam proses (aplikasi + DB dari .env), dengan batas laju dilonggarkan khusus untuk
evaluasi. Semua sesi sementara dihapus di akhir. Kode keluar 1 bila ada kasus gate/persona yang
tidak sesuai (target PRD: 100%). Hasil RAG hanya DILAPORKAN apa adanya; laporan CSV punya kolom
`nilai_manual` untuk penilaian akurasi jawaban oleh manusia.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, Batas, get_app_config, get_settings
from app.evaluasi import golden
from app.main import create_app
from app.services import persona as modul_persona

LONGGAR = Batas(maks=100_000, jendela_detik=60)


def _klien_evaluasi():
    settings, config = get_settings(), get_app_config()
    rl = config.rate_limit.model_copy(
        update={
            "per_sesi": LONGGAR,
            "per_ip": LONGGAR,
            "buat_sesi_per_ip": LONGGAR,
            "llm_per_sesi": LONGGAR,
        }
    )
    app = create_app(settings, config.model_copy(update={"rate_limit": rl}))
    return settings, app


def _cetak(judul: str, hasil: list[golden.Hasil]) -> bool:
    ringkas = golden.ringkas_gate(hasil)
    print(f"\n== {judul}: {ringkas['lulus']}/{ringkas['total']} sesuai ({ringkas['persen']}%)")
    for h in hasil:
        if not h.ok:
            print(f"   [BEDA] {h.id}: {h.detail}")
    return ringkas["lulus"] == ringkas["total"]


def _status_verifikasi() -> None:
    kasus = golden.muat_kasus_gate()
    persona = modul_persona.muat_semua()
    k_ok = sum(k.terverifikasi for k in kasus)
    p_ok = sum(p.harapan.hasil_terverifikasi for p in persona)
    print(
        f"\nVerifikasi manusia: {k_ok}/{len(kasus)} kasus gate, {p_ok}/{len(persona)} persona. "
        "Harapan yang belum diverifikasi tetap hanya kunci regresi, bukan klaim kebenaran."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rag", action="store_true", help="sertakan evaluasi RAG (memakai kuota API)")
    ap.add_argument("--hanya", choices=["gate", "persona", "rag"], help="jalankan satu bagian saja")
    ap.add_argument("--laporan", default=str(ROOT_DIR / "reports"), help="folder laporan CSV RAG")
    ap.add_argument("--golden-rag", default=str(golden.GOLDEN_RAG_CSV))
    a = ap.parse_args(argv)

    jalankan_gate = a.hanya in (None, "gate")
    jalankan_persona = a.hanya in (None, "persona")
    jalankan_rag = a.rag or a.hanya == "rag"

    settings, app = _klien_evaluasi()
    semua_sesuai = True
    with TestClient(app) as client:
        if jalankan_gate:
            semua_sesuai &= _cetak(
                "Gate (kasus uji)", golden.jalankan_kasus_gate(client, golden.muat_kasus_gate())
            )
        if jalankan_persona:
            hasil: list[golden.Hasil] = []
            with Session(app.state.engine) as db:
                for p in modul_persona.muat_semua():
                    hasil += golden.jalankan_persona(client, db, p)
            semua_sesuai &= _cetak("Persona demo", hasil)
        if jalankan_gate or jalankan_persona:
            _status_verifikasi()

        if jalankan_rag:
            if not settings.gemini_api_key:
                print("\nGEMINI_API_KEY belum diisi: RAG tidak dievaluasi.", file=sys.stderr)
                return 2
            soal = golden.muat_soal_rag(Path(a.golden_rag))
            print(f"\n== RAG: {len(soal)} pertanyaan dari {Path(a.golden_rag).name}")
            for kurang in golden.periksa_kecukupan(soal):
                print(f"   [KURANG] {kurang}")
            hasil_rag = golden.jalankan_rag(client, soal)
            path = Path(a.laporan) / f"golden_rag_{datetime.now():%Y%m%d-%H%M%S}.csv"
            golden.tulis_laporan_rag(hasil_rag, path)
            for nama, r in golden.ringkas_rag(hasil_rag).items():
                print(f"   {nama}: {r}")
            print(f"   Laporan: {path} (isi kolom nilai_manual untuk akurasi jawaban)")
    return 0 if semua_sesuai else 1


if __name__ == "__main__":
    sys.exit(main())
