"""Helper tes API bersama."""

from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import ROOT_DIR

CONSENT = {"consent": True, "consent_version": "2026-10-13"}
SEED_ASLI = ROOT_DIR / "data" / "seed"


def _seed_netral() -> tempfile.TemporaryDirectory:
    """Salinan data/seed dengan SEMUA terakhir_diverifikasi dikosongkan.

    Tes perilaku mesin memakai ini agar hasilnya tidak bergantung pada apakah tim data sudah mengisi
    tanggal verifikasi. Tes yang memeriksa data asli memakai SEED_ASLI.
    """
    tmp = tempfile.TemporaryDirectory(prefix="jalurku-seed-netral-")
    for sumber in SEED_ASLI.glob("*.csv"):
        mentah = sumber.read_bytes()
        teks = mentah.decode("utf-8-sig")
        pembaca = csv.DictReader(io.StringIO(teks, newline=""))
        if not pembaca.fieldnames or "terakhir_diverifikasi" not in pembaca.fieldnames:
            (Path(tmp.name) / sumber.name).write_bytes(mentah)
            continue
        baris = list(pembaca)
        with (Path(tmp.name) / sumber.name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=pembaca.fieldnames, lineterminator="\n")
            w.writeheader()
            for b in baris:
                b["terakhir_diverifikasi"] = ""
                w.writerow(b)
    return tmp


_SEED_NETRAL = _seed_netral()  # dibersihkan otomatis saat proses tes berakhir
SEED_DIR = Path(_SEED_NETRAL.name)
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
