"""scripts.siapkan_demo: sesi persona demo berumur panjang dan alur demo yang konsisten."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models as m
from app.services import persona as modul_persona
from scripts import siapkan_demo as demo
from tests.helpers import masuk

pytestmark = pytest.mark.db


def test_config_umur_sesi_demo_lebih_panjang_dari_sesi_publik(app_config):
    assert app_config.sesi.ttl_demo_jam == 72 > app_config.sesi.ttl_jam
    assert (
        app_config.llm.cache_ttl_detik >= app_config.sesi.ttl_demo_jam * 3600
    )  # cache tahan sepanjang demo


def test_sesi_demo_dibuat_di_db_dengan_ttl_demo_dan_bisa_dipakai(
    app_seed, clean_db, test_database_url
):
    token, sampai = demo.buat_sesi_demo(test_database_url, 72)
    h = {"Authorization": f"Bearer {token}"}
    assert app_seed.get("/api/v1/session", headers=h).status_code == 200  # token valid di API
    kedaluwarsa = datetime.fromisoformat(sampai)
    assert timedelta(hours=71, minutes=59) < kedaluwarsa - datetime.now(UTC) <= timedelta(hours=72)
    with Session(clean_db) as db:
        baris = db.query(m.Sesi).one()
        assert baris.consent_version == demo.CONSENT_DEMO


def test_sesi_publik_tetap_memakai_ttl_biasa(app_seed, app_config):
    masuk(app_seed)
    r = app_seed.post(
        "/api/v1/session", json={"consent": True, "consent_version": demo.CONSENT_DEMO}
    ).json()
    assert (
        r["sisa_detik"] <= app_config.sesi.ttl_jam * 3600
    )  # tidak ada jalan pintas 72 jam lewat API


def test_alur_demo_keputusan_identik_antar_sesi_dan_tanpa_penulisan_narasi_manual(app_seed):
    p = modul_persona.muat("rani")
    hasil = []
    for _ in range(2):
        token, _ = demo.buat_sesi_demo(app_seed.app.state.settings.database_url, 1)
        h = {"Authorization": f"Bearer {token}"}
        demo.muat_persona_ke_sesi(app_seed, h, p)
        hasil.append(demo.alur_demo(app_seed, h, p, demo.PERTANYAAN_BAWAAN))
    a, b = hasil
    assert a.keputusan_hash == b.keputusan_hash and len(a.keputusan_hash) == 16
    # Tanpa kunci Gemini seluruh teks adalah fallback bawaan aplikasi, bukan tulisan skrip.
    assert a.narasi_fallback is True and a.fallback_llm >= 1
    assert set(a.jawaban) == {*demo.PERTANYAAN_BAWAAN, demo.PERTANYAAN_KENAPA}


def test_kosongkan_cache_menghapus_semua_baris(clean_db, test_database_url):
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO llm_cache (key_hash, respons, ttl_detik) VALUES "
                "('a', '{}'::jsonb, 60), ('b', '{}'::jsonb, 60)"
            )
        )
    assert demo.kosongkan_cache(test_database_url) == 2


def test_kemiripan_teks():
    assert demo.kemiripan("sama persis", "sama persis") == 1.0
    assert demo.kemiripan("abc", "xyz") < 0.1
