"""Persona demo: hasil mesin sama dengan `harapan` di config/personas/*.json."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.evaluasi.golden import jalankan_persona
from app.services import persona as modul_persona

PERSONA = modul_persona.muat_semua()


@pytest.mark.parametrize("p", PERSONA, ids=lambda p: p.id)
def test_persona_sesuai_harapan(app_seed, clean_db, p):
    with Session(clean_db) as db:
        hasil = jalankan_persona(app_seed, db, p)
    assert hasil, "persona tanpa harapan yang diuji"
    beda = [f"{h.id}: {h.detail}" for h in hasil if not h.ok]
    assert not beda, "\n".join(beda)


def test_persona_menguji_gate_dan_penilaian(app_seed, clean_db):
    dimas = modul_persona.muat("dimas")
    with Session(clean_db) as db:
        ids = {h.id for h in jalankan_persona(app_seed, db, dimas)}
    assert {"persona:dimas:gate:SNBP", "persona:dimas:gate:SNBT"} <= ids
    assert "persona:dimas:penilaian:SNBT:ui-v-akuntansi-d3" in ids


def test_harapan_persona_yang_salah_terdeteksi(app_seed, clean_db):
    budi = modul_persona.muat("budi")
    palsu = budi.model_copy(
        update={"harapan": budi.harapan.model_copy(update={"gate": {"SNBT": "lolos"}})}
    )
    with Session(clean_db) as db:
        (h,) = [x for x in jalankan_persona(app_seed, db, palsu) if ":gate:" in x.id]
    assert not h.ok and "tidak_memenuhi_syarat != lolos" in h.detail


def test_persona_tanpa_rules_di_db_dilaporkan_bukan_dilempar(client, clean_db):
    """DB kosong (ingest belum jalan): pesan jelas, bukan exception."""
    rani = modul_persona.muat("rani")
    with Session(clean_db) as db:
        hasil = [h for h in jalankan_persona(client, db, rani) if ":gate:" in h.id]
    assert hasil and all(not h.ok and "ingest" in h.detail for h in hasil)
