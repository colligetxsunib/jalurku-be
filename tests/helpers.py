"""Helper tes API bersama."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import ROOT_DIR

CONSENT = {"consent": True, "consent_version": "2026-10-13"}
SEED_DIR = ROOT_DIR / "data" / "seed"
PERSONA_DIR = ROOT_DIR / "config" / "personas"


def persona(nama: str) -> dict:
    return json.loads((PERSONA_DIR / f"{nama}.json").read_text(encoding="utf-8"))


BERKAS_KRITIS = (
    "config_ketentuan.csv",
    "rule_gate.csv",
    "dokumen_wajib.csv",
    "acuan_skor_snbt.csv",
)


def salin_seed_terverifikasi(
    tujuan: Path, berkas: tuple[str, ...] = BERKAS_KRITIS, tanggal: str = "2026-10-13"
) -> Path:
    """Salinan data/seed di `tujuan` dengan terakhir_diverifikasi diisi pada `berkas` saja.

    Hanya untuk tes (mensimulasikan manusia yang sudah memverifikasi). Berkas asli tidak diubah.
    """
    tujuan.mkdir(parents=True, exist_ok=True)
    for sumber in SEED_DIR.glob("*.csv"):
        if sumber.name not in berkas:
            shutil.copy(sumber, tujuan / sumber.name)
            continue
        with sumber.open(encoding="utf-8", newline="") as f:
            pembaca = csv.DictReader(f)
            kolom = list(pembaca.fieldnames or [])
            baris = list(pembaca)
        if "terakhir_diverifikasi" not in kolom:
            kolom.append("terakhir_diverifikasi")
        for b in baris:
            if not b.get("terakhir_diverifikasi"):
                b["terakhir_diverifikasi"] = tanggal
        with (tujuan / sumber.name).open("w", encoding="utf-8", newline="") as f:
            penulis = csv.DictWriter(f, fieldnames=kolom, lineterminator="\n")
            penulis.writeheader()
            penulis.writerows(baris)
    return tujuan


def masuk(c: TestClient) -> dict[str, str]:
    """Buat sesi baru dan kembalikan header Authorization."""
    r = c.post("/api/v1/session", json=CONSENT)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def put_profil(c: TestClient, h: dict[str, str], **body):
    return c.put("/api/v1/profile", json=body, headers=h)


def muat_persona(c: TestClient, nama: str) -> dict[str, str]:
    """Sesi baru + profil persona (seperti tombol 'Muat persona demo')."""
    h = masuk(c)
    r = put_profil(c, h, **persona(nama)["profil"])
    assert r.status_code == 200, r.text
    return h


def analyze(c: TestClient, h, targets, override=None):
    body: dict = {"targets": targets}
    if override is not None:
        body["override"] = override
    return c.post("/api/v1/analyze", json=body, headers=h)
