"""Task 17: skrip seed persona dan ekspor halaman statis persona fiktif."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from app.evaluasi import halaman_statis
from app.services import persona as modul_persona
from scripts import export_persona_static, seed_personas
from scripts.export_persona_static import ExportError, ekspor_persona, tulis_halaman
from scripts.seed_personas import seed_persona
from tests.helpers import muat_persona


def tanpa_css(html: str) -> str:
    """Teks yang tampil: tanpa CSS (width:100%) dan tanpa atribut href (%20 pada URL)."""
    return re.sub(r'href="[^"]*"', "", re.sub(r"(?s)<style>.*?</style>", "", html))


def hitung(engine: Engine, tabel: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {tabel}")).scalar()  # noqa: S608


# ------------------------------------------------------------------ halaman statis (murni)


def ringkasan_contoh(**ubah) -> dict:
    pilihan = {
        "jalur": "SNBT",
        "urutan": 1,
        "prodi_id": "x",
        "prodi": "Ilmu <script>alert(1)</script> & Co",
        "ptn": 'PTN "Uji"',
        "jenjang": "S1",
        "program": "akademik",
        "status_gate": "lolos",
        "kategori": "reach",
        "keyakinan": "rendah",
        "indikatif": True,
        "alasan": "Alasan <b>tebal</b>",
        "gap": None,
        "sumber": [],
        "terakhir_diverifikasi": None,
        "status_verifikasi": "belum_diverifikasi",
    }
    dasar = {
        "pilihan_akhir": [pilihan],
        "alasan": ["SNBT: 1 pilihan"],
        "narasi": "Narasi <i>uji</i>.",
        "strategi": [
            {
                "jalur": "SNBT",
                "temuan": [{"tingkat": "peringatan", "pesan": "Pesan <x>", "kode": "k"}],
            }
        ],
        "fokus_persiapan": [{"jalur": "SNBT", "jenis": "data", "pesan": "Isi <data>"}],
        "dokumen_syarat": [
            {
                "jalur": "SNBT",
                "nama": "Dokumen <img src=x onerror=alert(1)>",
                "sumber_url": "javascript:alert(1)",
                "status_verifikasi": "belum_diverifikasi",
            },
            {
                "jalur": "SNBT",
                "nama": "Dokumen aman",
                "sumber_url": "https://contoh.id/a?x=1&y=2",
                "status_verifikasi": "terverifikasi",
            },
        ],
        "catatan": ["Catatan <u>"],
    }
    return dasar | ubah


def test_render_meng_escape_semua_teks_dan_menolak_tautan_berbahaya():
    html = halaman_statis.render_ringkasan(
        modul_persona.muat("rani"), ringkasan_contoh(), "2026-10-13 10:00 UTC"
    )
    assert "<script>" not in html and "<img" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html and "&amp; Co" in html and "&quot;Uji&quot;" in html
    assert 'href="javascript:' not in html.lower()
    assert 'href="https://contoh.id/a?x=1&amp;y=2"' in html
    assert 'rel="noopener noreferrer"' in html


def test_render_memuat_penanda_fiktif_penutup_dan_tanpa_sumber_eksternal():
    html = halaman_statis.render_ringkasan(
        modul_persona.muat("rani"), ringkasan_contoh(), "2026-10-13 10:00 UTC"
    )
    assert '<html lang="id">' in html and 'name="viewport"' in html
    assert "persona fiktif" in html and "bukan data siswa nyata" in html
    assert "bukan dari AI" in html and "heuristik indikatif" in html
    assert "belum diverifikasi tim data" in html and "terverifikasi tim data" in html
    assert 'name="robots" content="noindex"' in html
    assert (
        re.search(r"<(script|link|iframe|img|source|object|embed)\b", html) is None
    )  # tanpa JS/sumber eksternal
    assert "<caption>" in html and 'scope="col"' in html  # tabel dapat dibaca pembaca layar
    assert re.search(r"\d\s*%", tanpa_css(html)) is None  # tanpa klaim persentase


def test_kategori_tak_dikenal_dan_kosong_tetap_terbaca():
    r = ringkasan_contoh()
    r["pilihan_akhir"][0] |= {"kategori": None, "keyakinan": None, "status_gate": "data_kurang"}
    html = halaman_statis.render_ringkasan(modul_persona.muat("sinta"), r, "t")
    assert "Belum dinilai" in html and "Data belum lengkap" in html


def test_indeks_menautkan_halaman_lokal():
    daftar = [(modul_persona.muat("rani"), "rani.html"), (modul_persona.muat("budi"), "budi.html")]
    html = halaman_statis.render_indeks(daftar, "t")
    assert 'href="rani.html"' in html and 'href="budi.html"' in html
    assert "Tidak ada data pengguna" in html


# ------------------------------------------------------------------ seed persona (API)


@pytest.mark.db
def test_seed_persona_membuat_sesi_dan_profil(app_seed):
    h = seed_persona(app_seed, modul_persona.muat("dimas"))
    auth = {"Authorization": f"Bearer {h.token}"}
    r = app_seed.get("/api/v1/profile", headers=auth)
    assert r.status_code == 200 and r.json()["profil"]["tahun_lulus"] == 2026
    assert h.sisa_detik > 0 and h.strategi == {}


@pytest.mark.db
def test_seed_persona_dengan_strategi_siap_diringkas(app_seed):
    h = seed_persona(app_seed, modul_persona.muat("dimas"), simpan_strategi=True)
    assert set(h.strategi) == {"SNBP", "SNBT"}
    r = app_seed.post("/api/v1/summary", json={}, headers={"Authorization": f"Bearer {h.token}"})
    assert r.status_code == 200 and len(r.json()["pilihan_akhir"]) == 5


@pytest.mark.db
def test_seed_persona_sinta_melaporkan_data_kurang_tanpa_menebak(app_seed):
    h = seed_persona(app_seed, modul_persona.muat("sinta"))
    assert any(h.data_kurang.values())


@pytest.mark.db
def test_seed_persona_gagal_dilaporkan_bukan_diam(app_seed):
    """Kegagalan HTTP (prodi tidak ada) menjadi SeedError yang jelas, bukan diam atau traceback."""
    p = modul_persona.muat("rani").model_copy(update={"strategi_demo": {"SNBT": ["tidak-ada"]}})
    with pytest.raises(seed_personas.SeedError, match="POST /strategy SNBT gagal"):
        seed_persona(app_seed, p, simpan_strategi=True)


def test_cli_seed_persona_tidak_dikenal_dan_server_mati(capsys):
    assert seed_personas.main(["--persona", "tidak-ada"]) == 2
    assert "tidak ditemukan" in capsys.readouterr().err
    assert seed_personas.main(["--persona", "rani", "--base-url", "http://127.0.0.1:1"]) == 1
    assert "[GAGAL] rani" in capsys.readouterr().out


# ------------------------------------------------------------------ ekspor statis


@pytest.mark.db
def test_ekspor_persona_mengembalikan_ringkasan_dan_menghapus_sesi(app_seed, clean_db):
    r = ekspor_persona(app_seed, modul_persona.muat("dimas"))
    assert {p["jalur"] for p in r["pilihan_akhir"]} == {"SNBP", "SNBT"}
    assert r["narasi_fallback"] is True  # tanpa kunci API: template, deterministik
    assert hitung(clean_db, "sessions") == hitung(clean_db, "profiles") == 0
    assert hitung(clean_db, "strategies") == 0


@pytest.mark.db
def test_ekspor_persona_tanpa_strategi_demo_ditolak(app_seed):
    p = modul_persona.muat("rani").model_copy(update={"strategi_demo": {}})
    with pytest.raises(ExportError, match="strategi_demo"):
        ekspor_persona(app_seed, p)


@pytest.mark.db
def test_ekspor_gagal_tetap_menghapus_sesi(app_seed, clean_db):
    p = modul_persona.muat("rani").model_copy(update={"strategi_demo": {"SNBT": ["tidak-ada"]}})
    with pytest.raises(ExportError, match="POST /strategy SNBT gagal"):
        ekspor_persona(app_seed, p)
    assert hitung(clean_db, "sessions") == 0


@pytest.mark.db
def test_tulis_halaman_semua_persona(app_seed, tmp_path: Path):
    daftar = modul_persona.muat_semua()
    ditulis = tulis_halaman(daftar, app_seed, tmp_path / "demo_statis", "2026-10-13 10:00 UTC")
    nama = {p.name for p in ditulis}
    assert nama == {"index.html", "rani.html", "dimas.html", "budi.html", "sinta.html"}
    for p in ditulis:
        html = p.read_text(encoding="utf-8")
        assert "persona fiktif" in html
        assert not re.search(r"Bearer|token|session_id|<script", html, re.IGNORECASE)
        assert re.search(r"\d\s*%", tanpa_css(html)) is None
    rani = (tmp_path / "demo_statis" / "rani.html").read_text(encoding="utf-8")
    assert "Ilmu Komputer" in rani and "Reach" in rani and "Match" in rani
    budi = (tmp_path / "demo_statis" / "budi.html").read_text(encoding="utf-8")
    assert "Belum memenuhi syarat" in budi  # kasus gagal ditampilkan jujur, bukan disembunyikan
    sinta = (tmp_path / "demo_statis" / "sinta.html").read_text(encoding="utf-8")
    assert "Data belum lengkap" in sinta


@pytest.mark.db
def test_halaman_deterministik_untuk_waktu_yang_sama(app_seed, tmp_path: Path):
    p = [modul_persona.muat("dimas")]
    a = tulis_halaman(p, app_seed, tmp_path / "a", "t")[0].read_text(encoding="utf-8")
    b = tulis_halaman(p, app_seed, tmp_path / "b", "t")[0].read_text(encoding="utf-8")
    assert re.sub(r"Dibuat .*?\.", "", a) == re.sub(r"Dibuat .*?\.", "", b)


def test_cli_ekspor_persona_tidak_dikenal(capsys):
    assert export_persona_static.main(["--persona", "tidak-ada"]) == 2
    assert "tidak ditemukan" in capsys.readouterr().err


@pytest.mark.db
def test_muat_persona_helper_tes_masih_bekerja(app_seed):
    assert muat_persona(app_seed, "rani")["Authorization"].startswith("Bearer ")
