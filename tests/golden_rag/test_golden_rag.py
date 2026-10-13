"""Golden set RAG (PRD bagian 14): pengukuran sumber, kejujuran, dan keputusan dari mesin aturan.

Yang diuji di sini adalah PENGUKURNYA (skor otomatis, laporan, kecukupan set). Akurasi RAG yang
sebenarnya hanya bisa diukur dengan dokumen resmi ter-ingest dan GEMINI_API_KEY nyata
(`python -m scripts.run_golden_set --rag`) lalu dinilai manusia.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.evaluasi import golden
from app.evaluasi.golden import (
    GoldenError,
    SoalRag,
    jalankan_rag,
    muat_soal_rag,
    nilai_satu,
    periksa_kecukupan,
    ringkas_rag,
    tulis_laporan_rag,
)
from app.ingest.service import ingest_direktori
from app.llm.prompts import JawabanRAG
from app.main import create_app
from tests.conftest import make_settings
from tests.fakes import FakeLLM
from tests.helpers import SEED_DIR

URL = "https://files.snpmb.id/web2026/Paparan%20Informasi%20SNPMB%202026%20untuk%20Peluncuran.pdf"


def soal(tipe="dalam_cakupan", jawaban="Dua program studi.", url=URL, halaman=None, no=1):
    return SoalRag(no, "Pertanyaan?", jawaban, url, halaman, tipe)


def respons(**kw):
    dasar = {
        "jawaban": "SNBP 2026 memiliki 2 pilihan program studi.",
        "yakin": True,
        "jenis_jawaban": "rag",
        "fallback": False,
        "sumber": [{"judul": "Paparan", "url": URL, "halaman": 12}],
    }
    return dasar | kw


# ------------------------------------------------------------------ muat & kecukupan


def test_golden_csv_yang_ada_terbaca():
    daftar = muat_soal_rag()
    assert len(daftar) == 12
    assert {s.tipe for s in daftar} == {"dalam_cakupan", "di_luar_cakupan", "keputusan"}
    assert [s.nomor for s in daftar] == list(range(1, 13))
    assert all(s.sumber_url for s in daftar if s.tipe == "dalam_cakupan")


def lengkap(n_luar=5, n_putusan=3, total=20):
    daftar = [soal("di_luar_cakupan", url=None, no=i) for i in range(n_luar)]
    daftar += [soal("keputusan", url=None, no=100 + i) for i in range(n_putusan)]
    daftar += [soal(halaman=3, no=200 + i) for i in range(total - n_luar - n_putusan)]
    return daftar


def test_kecukupan_memenuhi_syarat_prd():
    assert periksa_kecukupan(lengkap()) == []


@pytest.mark.parametrize(
    "daftar, kata",
    [
        (lengkap(total=19), "hanya 19 pertanyaan"),
        (lengkap(n_luar=4, total=20), "4 pertanyaan di luar cakupan"),
        (lengkap(n_putusan=2, total=20), "2 pertanyaan keputusan"),
        ([soal(halaman=None)] + lengkap()[1:], "belum diisi halamannya"),
        ([soal(url=None, halaman=1)] + lengkap()[1:], "tanpa sumber_url"),
    ],
)
def test_kecukupan_melaporkan_kekurangan(daftar, kata):
    assert any(kata in k for k in periksa_kecukupan(daftar))


def test_csv_tidak_valid_ditolak(tmp_path: Path):
    def tulis(baris: list[list[str]]) -> Path:
        p = tmp_path / "g.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["pertanyaan", "jawaban_benar", "sumber_url", "halaman", "tipe"])
            w.writerows(baris)
        return p

    with pytest.raises(GoldenError, match="tipe tidak dikenal"):
        muat_soal_rag(tulis([["Apa?", "Itu", "", "", "aneh"]]))
    with pytest.raises(GoldenError, match="halaman harus angka"):
        muat_soal_rag(tulis([["Apa?", "Itu", URL, "dua belas", "dalam cakupan"]]))
    assert muat_soal_rag(tulis([["Apa?", "Itu", URL, "12", "dalam cakupan"]]))[0].halaman == 12
    with pytest.raises(GoldenError, match="tidak bisa dibaca"):
        muat_soal_rag(tmp_path / "tidak-ada.csv")


# ------------------------------------------------------------------ skor otomatis


def test_di_luar_cakupan_lulus_hanya_bila_tidak_yakin():
    s = soal("di_luar_cakupan", url=None)
    assert nilai_satu(s, respons(yakin=False)).lulus_otomatis is True
    assert nilai_satu(s, respons(yakin=True)).lulus_otomatis is False


def test_keputusan_lulus_hanya_bila_dijawab_mesin_aturan():
    s = soal("keputusan", url=None)
    assert nilai_satu(s, respons(jenis_jawaban="mesin_aturan", yakin=False)).lulus_otomatis is True
    assert nilai_satu(s, respons(jenis_jawaban="rag")).lulus_otomatis is False


def test_dalam_cakupan_lulus_bila_yakin_sumber_halaman_dan_angka_cocok():
    s = soal(jawaban="Dua pilihan, yaitu 2 prodi.", halaman=12)
    h = nilai_satu(s, respons())
    assert (h.sumber_cocok, h.halaman_cocok, h.angka_cocok, h.lulus_otomatis) == (
        True,
        True,
        True,
        True,
    )


def test_url_dibandingkan_setelah_decode_dan_tanpa_beda_kapital_atau_garis_miring_akhir():
    s = soal(url=URL.replace("%20", " ") + "/")
    assert nilai_satu(s, respons()).sumber_cocok is True


@pytest.mark.parametrize(
    "ubah",
    [
        {"yakin": False},
        {"sumber": [{"judul": "Lain", "url": "https://contoh.id/lain.pdf", "halaman": 12}]},
        {"sumber": []},
        {"jawaban": "Tidak tahu."},
    ],
)
def test_dalam_cakupan_gagal_bila_salah_satu_syarat_tak_terpenuhi(ubah):
    s = soal(jawaban="Dua pilihan, yaitu 2 prodi.", halaman=12)
    assert nilai_satu(s, respons(**ubah)).lulus_otomatis is False


def test_halaman_salah_gagal():
    s = soal(halaman=99)
    h = nilai_satu(s, respons())
    assert h.halaman_cocok is False and h.lulus_otomatis is False


def test_jawaban_tanpa_angka_kunci_tidak_diperiksa_angkanya():
    h = nilai_satu(soal(jawaban="Ya, boleh."), respons(jawaban="Boleh."))
    assert h.angka_cocok is None and h.lulus_otomatis is True


def test_angka_desimal_dan_koma_diperlakukan_sama():
    h = nilai_satu(soal(jawaban="Skor 12,5 poin."), respons(jawaban="Skornya 12.5."))
    assert h.angka_cocok is True


def test_fallback_dicatat_dan_tidak_lulus():
    h = nilai_satu(soal(), respons(yakin=False, fallback=True, sumber=[]))
    assert h.lulus_otomatis is False and "fallback" in h.catatan


def test_query_gagal_dilaporkan():
    h = nilai_satu(soal(), None, status=503)
    assert h.lulus_otomatis is False and "503" in h.catatan


def test_ringkasan_metrik():
    hasil = [
        nilai_satu(soal("di_luar_cakupan", url=None), respons(yakin=False)),
        nilai_satu(soal("di_luar_cakupan", url=None), respons(yakin=True)),
        nilai_satu(soal("keputusan", url=None), respons(jenis_jawaban="mesin_aturan")),
        nilai_satu(soal(), respons()),
        nilai_satu(soal(), respons(yakin=False, fallback=True)),
    ]
    r = ringkas_rag(hasil)
    assert r["kejujuran_di_luar_cakupan"] == {"lulus": 1, "total": 2, "persen": 50.0}
    assert r["keputusan_dari_mesin_aturan"]["persen"] == 100.0
    assert r["dalam_cakupan_proksi_otomatis"] == {"lulus": 1, "total": 2, "persen": 50.0}
    assert r["fallback"] == 1 and r["total"] == 5


def test_ringkasan_tanpa_pertanyaan_tidak_membagi_nol():
    assert ringkas_rag([])["kejujuran_di_luar_cakupan"]["persen"] is None


def test_laporan_csv_punya_kolom_nilai_manual_kosong(tmp_path: Path):
    s = SoalRag(1, 'Tanya, "ini"?\nbaris dua', "Jawab, 2 hal", URL, 12, "dalam_cakupan")
    path = tmp_path / "sub" / "laporan.csv"
    tulis_laporan_rag([nilai_satu(s, respons(jawaban="Jawab, 2 hal"))], path)
    with path.open(encoding="utf-8", newline="") as f:
        (baris,) = list(csv.DictReader(f))
    assert list(baris) == golden.KOLOM_LAPORAN
    assert baris["nilai_manual"] == "" and baris["lulus_otomatis"] == "True"
    assert baris["pertanyaan"] == 'Tanya, "ini"?\nbaris dua'  # CSV aman untuk koma/kutip/baris baru
    assert "hal. 12" in baris["sumber_sistem"]


# ------------------------------------------------------------------ terhadap aplikasi (DB)


@pytest.mark.db
def test_tanpa_llm_kejujuran_dan_keputusan_tetap_lulus_dalam_cakupan_tidak(app_seed):
    """Tanpa kunci API: sistem tidak mengarang. Di luar cakupan dan keputusan lulus, RAG tidak."""
    hasil = jalankan_rag(app_seed, muat_soal_rag())
    r = ringkas_rag(hasil)
    assert r["kejujuran_di_luar_cakupan"]["persen"] == 100.0
    assert r["keputusan_dari_mesin_aturan"]["persen"] == 100.0
    assert r["dalam_cakupan_proksi_otomatis"]["lulus"] == 0
    assert all(h.yakin is False for h in hasil if h.soal.tipe == "dalam_cakupan")


@pytest.mark.db
def test_sesi_evaluasi_dihapus(app_seed, clean_db: Engine):
    from sqlalchemy import text

    jalankan_rag(app_seed, muat_soal_rag()[:3])
    with clean_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sessions")).scalar() == 0


@pytest.mark.db
def test_jalur_rag_penuh_dengan_fake_llm(clean_db: Engine, app_config: AppConfig):
    """Dokumen ter-ingest + LLM palsu: pertanyaan pertama lulus otomatis (sumber, halaman, angka)."""
    pertanyaan = muat_soal_rag()[0]  # "Berapa jumlah pilihan program studi di SNBP 2026?"
    vektor = [1.0] + [0.0] * 767
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
        db.add(
            m.RagChunk(
                dokumen_id="snpmb-paparan-2026",
                urutan=0,
                teks="SNBP 2026 memiliki 2 pilihan program studi dari satu atau dua PTN.",
                halaman=12,
                embedding=vektor,
                embedding_model="gemini-embedding-001",
                sumber_url=db.get(m.DokumenSumber, "snpmb-paparan-2026").url,
                tahun_siklus=2026,
            )
        )
        db.commit()

    def balas(prompt, system, skema):
        return JawabanRAG(
            jawaban="Dua program studi dari satu atau dua PTN (2 pilihan).",
            cukup_informasi=True,
            saran_pertanyaan=[],
        ).model_dump_json()

    fake = FakeLLM(peta_embed={pertanyaan.pertanyaan: vektor}, balasan=balas)
    app = create_app(make_settings(), app_config, clean_db, llm_client=fake)
    benar = SoalRag(
        pertanyaan.nomor,
        pertanyaan.pertanyaan,
        "Dua program studi, 2 pilihan.",
        URL,
        12,
        "dalam_cakupan",
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        (h,) = jalankan_rag(c, [benar])
    assert h.yakin is True and h.fallback is False
    assert (h.sumber_cocok, h.halaman_cocok, h.angka_cocok, h.lulus_otomatis) == (
        True,
        True,
        True,
        True,
    )
