"""Buat sesi demo berisi profil persona fiktif di API yang sedang berjalan (untuk rekam video / uji manual).

    python -m scripts.seed_personas --persona rani --base-url http://localhost:8000
    python -m scripts.seed_personas --semua --simpan-strategi

Meniru tombol "Muat persona demo" (PRD bagian 13): POST /session lalu PUT /profile dengan data
persona; opsional menyimpan `strategi_demo` agar POST /summary langsung bisa dipakai. Mencetak token
sesi (fiktif, berlaku sesuai TTL) untuk dipakai sebagai `Authorization: Bearer <token>`.
Tidak ada data nyata: persona selalu fiktif.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services import persona as modul_persona
from app.services.persona import Persona

API = "/api/v1"
CONSENT = {"consent": True, "consent_version": "seed-persona"}


class SeedError(RuntimeError):
    pass


@dataclass
class HasilSeed:
    persona: str
    token: str
    sisa_detik: int
    data_kurang: dict[str, list[str]]
    strategi: dict[str, str] = field(default_factory=dict)  # jalur -> strategy_id


def _harap(r: httpx.Response, kode: int, apa: str) -> dict[str, Any]:
    if r.status_code != kode:
        raise SeedError(f"{apa} gagal (HTTP {r.status_code}): {r.text[:200]}")
    return r.json() if r.content else {}


def seed_persona(client, persona: Persona, *, simpan_strategi: bool = False) -> HasilSeed:
    sesi = _harap(client.post(f"{API}/session", json=CONSENT), 201, "POST /session")
    header = {"Authorization": f"Bearer {sesi['token']}"}
    profil = _harap(
        client.put(f"{API}/profile", json=persona.profil, headers=header), 200, "PUT /profile"
    )
    hasil = HasilSeed(persona.id, sesi["token"], sesi["sisa_detik"], profil["data_kurang"])
    if simpan_strategi:
        for jalur, ids in persona.strategi_demo.items():
            body = {"jalur": jalur, "pilihan": [{"prodi_id": i} for i in ids], "simpan": True}
            d = _harap(
                client.post(f"{API}/strategy", json=body, headers=header),
                200,
                f"POST /strategy {jalur}",
            )
            hasil.strategi[jalur] = d["strategy_id"]
    return hasil


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    pilih = ap.add_mutually_exclusive_group(required=True)
    pilih.add_argument("--persona", help="id persona, mis. rani")
    pilih.add_argument("--semua", action="store_true", help="semua persona di config/personas")
    ap.add_argument("--simpan-strategi", action="store_true", help="simpan strategi_demo persona")
    ap.add_argument("--insecure", action="store_true", help="jangan verifikasi TLS")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args(argv)

    try:
        daftar = modul_persona.muat_semua() if a.semua else [modul_persona.muat(a.persona)]
    except modul_persona.PersonaError as exc:
        print(f"Persona: {exc}", file=sys.stderr)
        return 2

    gagal = False
    with httpx.Client(base_url=a.base_url, timeout=a.timeout, verify=not a.insecure) as client:
        for p in daftar:
            try:
                h = seed_persona(client, p, simpan_strategi=a.simpan_strategi)
            except (SeedError, httpx.HTTPError) as exc:
                gagal = True
                print(f"[GAGAL] {p.id}: {exc}")
                continue
            print(f"[OK] {p.id} ({p.nama}), sesi berlaku {h.sisa_detik // 3600} jam")
            print(f"     Authorization: Bearer {h.token}")
            kurang = {j: f for j, f in h.data_kurang.items() if f}
            print(f"     data_kurang: {kurang if kurang else 'tidak ada'}")
            for jalur, sid in h.strategi.items():
                print(f"     strategi {jalur}: {sid}")
    return 1 if gagal else 0


if __name__ == "__main__":
    sys.exit(main())
