"""Ekspor halaman HTML statis ringkasan persona fiktif (tautan untuk juri, PRD bagian 9).

    python -m scripts.export_persona_static                       # semua persona -> data/demo_statis/
    python -m scripts.export_persona_static --persona rani dimas
    python -m scripts.export_persona_static --dengan-llm          # narasi LLM bila GEMINI_API_KEY ada

Berjalan offline di dalam proses (aplikasi + DB dari .env): membuat sesi sementara, memuat profil
persona, menyimpan strategi_demo, mengambil POST /summary, merender HTML, lalu MENGHAPUS sesinya.
Halaman hasil disajikan nginx sebagai berkas statis di /demo-statis/, terpisah dari DB dan sesi.
Jalankan di mesin pengembangan (DB berisi seed), lalu salin folder data/demo_statis/ ke server:
docker-compose.prod.yml memasangnya read-only ke nginx. Secara default narasi memakai template agar
hasil deterministik dan tanpa kuota API.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import ROOT_DIR, get_app_config, get_settings
from app.evaluasi import halaman_statis
from app.llm.client import NullClient
from app.main import create_app
from app.services import persona as modul_persona
from app.services.persona import Persona

API = "/api/v1"
OUT_DEFAULT = ROOT_DIR / "data" / "demo_statis"


class ExportError(RuntimeError):
    pass


def ekspor_persona(client, persona: Persona) -> dict:
    """Respons POST /summary untuk persona. Sesi sementara selalu dihapus."""
    if not persona.strategi_demo:
        raise ExportError(f"persona '{persona.id}' tidak punya strategi_demo")
    r = client.post(f"{API}/session", json={"consent": True, "consent_version": "ekspor-statis"})
    if r.status_code != 201:
        raise ExportError(f"POST /session gagal (HTTP {r.status_code})")
    header = {"Authorization": f"Bearer {r.json()['token']}"}
    try:
        r = client.put(f"{API}/profile", json=persona.profil, headers=header)
        if r.status_code != 200:
            raise ExportError(f"PUT /profile gagal (HTTP {r.status_code}): {r.text[:200]}")
        for jalur, ids in persona.strategi_demo.items():
            body = {"jalur": jalur, "pilihan": [{"prodi_id": i} for i in ids], "simpan": True}
            r = client.post(f"{API}/strategy", json=body, headers=header)
            if r.status_code != 200:
                raise ExportError(f"POST /strategy {jalur} gagal (HTTP {r.status_code})")
        r = client.post(f"{API}/summary", json={}, headers=header)
        if r.status_code != 200:
            raise ExportError(f"POST /summary gagal (HTTP {r.status_code}): {r.text[:200]}")
        return r.json()
    finally:
        client.delete(f"{API}/session", headers=header)


def tulis_halaman(daftar: list[Persona], client, out: Path, dibuat: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    ditulis: list[Path] = []
    for p in daftar:
        ringkasan = ekspor_persona(client, p)
        path = out / f"{p.id}.html"
        path.write_text(halaman_statis.render_ringkasan(p, ringkasan, dibuat), encoding="utf-8")
        ditulis.append(path)
    indeks = out / "index.html"
    indeks.write_text(
        halaman_statis.render_indeks([(p, f"{p.id}.html") for p in daftar], dibuat),
        encoding="utf-8",
    )
    return [*ditulis, indeks]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--persona", nargs="+", help="id persona (default: semua)")
    ap.add_argument("--dengan-llm", action="store_true", help="narasi LLM bila kunci API ada")
    a = ap.parse_args(argv)

    try:
        daftar = (
            [modul_persona.muat(n) for n in a.persona] if a.persona else modul_persona.muat_semua()
        )
    except modul_persona.PersonaError as exc:
        print(f"Persona: {exc}", file=sys.stderr)
        return 2

    settings, config = get_settings(), get_app_config()
    app = create_app(settings, config, llm_client=None if a.dengan_llm else NullClient())
    dibuat = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    try:
        with TestClient(app) as client:
            ditulis = tulis_halaman(daftar, client, Path(a.out), dibuat)
    except ExportError as exc:
        print(f"[GAGAL] {exc}", file=sys.stderr)
        return 1
    for p in ditulis:
        print(f"[OK] {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
