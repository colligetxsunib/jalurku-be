"""Data asli di data/seed (bukan salinan netral): perilaku untuk prodi tanpa data acuan.

Keputusan tim 14 Oktober 2026: demo hanya UI; keketatan SNBP, sembilan PTN lain, dan acuan_skor
dikosongkan. Yang kosong harus tampil `belum_ada_acuan` dan tidak pernah dihitung terverifikasi.
Tes ini sengaja TIDAK bergantung pada apakah kolom tanggal verifikasi sudah diisi.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.ingest.service import ingest_direktori
from app.main import create_app
from tests.conftest import make_settings
from tests.helpers import SEED_ASLI, analyze, muat_persona

pytestmark = pytest.mark.db

IK = "ui-ilmu-komputer"
UI_TANPA_DATA = "ui-dkv"  # tidak ada di daftar SNBT UI


def baris_prodi() -> list[dict[str, str]]:
    with (SEED_ASLI / "prodi.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


PRODI_ITB = next(b["prodi_id"] for b in baris_prodi() if b["ptn_id"] == "itb")


@pytest.fixture()
def asli(clean_db: Engine, app_config: AppConfig) -> Iterator[TestClient]:
    with Session(clean_db) as db:
        hasil = ingest_direktori(db, SEED_ASLI)
        assert all(h.ok for h in hasil), [e for h in hasil for e in h.error]
    app = create_app(make_settings(), app_config, clean_db)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def penilaian(c, h, prodi: str, jalur: str) -> dict:
    r = analyze(c, h, [{"prodi_id": prodi, "jalur": [jalur]}])
    assert r.status_code == 200, r.text
    return r.json()["hasil"][0]


def test_seed_asli_masuk_tanpa_error_dan_prodi_tanpa_data_tidak_bertanggal(asli, clean_db: Engine):
    tanpa_data = {b["prodi_id"] for b in baris_prodi() if not b["daya_tampung"].strip()}
    assert UI_TANPA_DATA in tanpa_data and len(tanpa_data) == 154
    with Session(clean_db) as db:
        for p in db.query(m.Prodi).filter(m.Prodi.id.in_(tanpa_data)):
            assert p.terakhir_diverifikasi is None, p.id  # apa pun isi kolom tanggal di CSV
        assert db.query(m.ProdiJalur).count() == 31
        assert db.query(m.AcuanSkor).count() == 0


@pytest.mark.parametrize("jalur", ["SNBP", "SNBT"])
@pytest.mark.parametrize("prodi", [UI_TANPA_DATA, "ugm-ilmu-komputer", PRODI_ITB])
def test_prodi_tanpa_data_acuan_tampil_belum_ada_acuan_dan_belum_diverifikasi(asli, prodi, jalur):
    # persona Dimas sudah mengonfirmasi syarat prodi untuk SNBP, jadi gate SNBP juga lolos
    h = muat_persona(asli, "dimas")
    from tests.helpers import put_profil

    put_profil(asli, h, konfirmasi_syarat_prodi={prodi: True})
    assert _ada(asli, h, prodi), f"{prodi} tidak ada di katalog"
    hasil = penilaian(asli, h, prodi, jalur)
    assert hasil["gate"]["status"] == "lolos"
    p = hasil["penilaian"]
    assert p["kategori"] == "belum_ada_acuan" and p["keyakinan"] is None
    assert "Sistem tidak menebak" in p["alasan"]
    assert hasil["status_verifikasi"] == "belum_diverifikasi"
    assert hasil["terakhir_diverifikasi"] is None
    assert {
        "jenis": "keketatan",
        "url": None,
        "terakhir_diverifikasi": None,
        "status_verifikasi": "belum_diverifikasi",
    } in hasil["sumber_detail"]


def _ada(c, h, prodi: str) -> bool:
    return c.get(f"/api/v1/catalog/prodi/{prodi}", headers=h).status_code == 200


def test_snbp_ui_belum_ada_acuan_walau_snbt_ada_data(asli):
    """UI punya data SNBT, tidak punya data SNBP: SNBP `belum_ada_acuan`, SNBT dinilai."""
    h = muat_persona(asli, "dimas")
    snbp = penilaian(asli, h, "ui-teknik-industri", "SNBP")["penilaian"]
    snbt = penilaian(asli, h, "ui-teknik-industri", "SNBT")["penilaian"]
    assert snbp["kategori"] == "belum_ada_acuan" and snbp["tier"] is not None  # tier tetap tampil
    assert snbt["kategori"] in ("reach", "match", "safe")


def test_katalog_menandai_prodi_kosong_dan_prodi_berdata(asli):
    h = muat_persona(asli, "rani")
    kosong = asli.get(f"/api/v1/catalog/prodi/{UI_TANPA_DATA}", headers=h).json()
    assert kosong["keketatan"] == {} and kosong["status_acuan"] == "belum_ada_acuan"
    assert kosong["status_verifikasi"] == "belum_diverifikasi"
    berdata = asli.get(f"/api/v1/catalog/prodi/{IK}", headers=h).json()
    assert set(berdata["keketatan"]) == {"SNBT"}  # hanya SNBT, SNBP sengaja kosong
    assert berdata["keketatan"]["SNBT"]["rasio_peminat_per_kursi"] == pytest.approx(28.43)
    assert berdata["acuan"] is None  # acuan_skor dikosongkan (tidak ada passing grade resmi)


def test_ringkasan_dengan_prodi_kosong_jujur_tentang_data(asli):
    h = muat_persona(asli, "dimas")
    from tests.helpers import put_profil

    put_profil(asli, h, konfirmasi_syarat_prodi={UI_TANPA_DATA: True})
    r = asli.post(
        "/api/v1/strategy",
        json={
            "jalur": "SNBT",
            "pilihan": [{"prodi_id": "ui-teknik-industri"}, {"prodi_id": UI_TANPA_DATA}],
            "simpan": True,
        },
        headers=h,
    )
    assert r.status_code == 200
    s = asli.post("/api/v1/summary", json={}, headers=h).json()
    kosong = next(p for p in s["pilihan_akhir"] if p["prodi_id"] == UI_TANPA_DATA)
    assert (
        kosong["kategori"] == "belum_ada_acuan"
        and kosong["status_verifikasi"] == "belum_diverifikasi"
    )
    assert any(t["kode"] == "pilihan_belum_ada_acuan" for t in s["strategi"][0]["temuan"])
