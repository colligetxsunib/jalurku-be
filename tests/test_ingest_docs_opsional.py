"""scripts.ingest_docs: dokumen yang berkasnya belum ada (mis. snpmb-faq) dilewati, bukan error."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.ingest.service import ingest_direktori
from scripts import ingest_docs
from tests.helpers import SEED_DIR

pytestmark = pytest.mark.db

TEKS = "SNBP 2026 memiliki dua pilihan program studi. Peserta wajib memiliki akun SNPMB. " * 12


@pytest.fixture()
def terdaftar(clean_db):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))


def jalankan(test_database_url, folder, *tambahan):
    return ingest_docs.main(
        ["--dry-run", "--dir", str(folder), "--database-url", test_database_url, *tambahan]
    )


def test_berkas_hilang_dilewati_tanpa_error(terdaftar, test_database_url, tmp_path, capsys):
    (tmp_path / "snpmb-paparan-2026.txt").write_text(TEKS, encoding="utf-8")
    assert jalankan(test_database_url, tmp_path) == 0
    keluar = capsys.readouterr().out
    assert "[DRY]  snpmb-paparan-2026" in keluar
    assert "[LEWATI] snpmb-faq" in keluar and "[GAGAL]" not in keluar
    assert "dilewati karena berkasnya belum ada" in keluar


def test_dokumen_yang_diminta_eksplisit_tapi_berkasnya_hilang_juga_dilewati(
    terdaftar, test_database_url, tmp_path, capsys
):
    (tmp_path / "snpmb-paparan-2026.txt").write_text(TEKS, encoding="utf-8")
    kode = jalankan(test_database_url, tmp_path, "--dokumen", "snpmb-paparan-2026", "snpmb-faq")
    assert kode == 0 and "[LEWATI] snpmb-faq" in capsys.readouterr().out


def test_gagal_bila_tidak_ada_satu_pun_berkas(terdaftar, test_database_url, tmp_path, capsys):
    assert jalankan(test_database_url, tmp_path) == 1
    assert "tidak ada satu pun berkas" in capsys.readouterr().err


def test_kegagalan_lain_tetap_error(terdaftar, test_database_url, tmp_path, capsys):
    (tmp_path / "snpmb-paparan-2026.txt").write_text("   ", encoding="utf-8")  # tanpa teks
    assert jalankan(test_database_url, tmp_path, "--dokumen", "snpmb-paparan-2026") == 1
    assert "[GAGAL] snpmb-paparan-2026" in capsys.readouterr().out
