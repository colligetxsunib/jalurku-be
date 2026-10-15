"""Data eksplorasi DRAF: pemuatan, penandaan di /explore, prioritas terhadap data resmi, fallback katalog."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR, AppConfig, ConfigError
from app.db import models as m
from app.ingest.service import ingest_direktori
from app.main import create_app
from app.services.draf_eksplorasi import LABEL_DRAF, NAMA_PRODI, NAMA_PROFESI, muat_draf
from scripts import buat_draf_eksplorasi as generator
from tests.conftest import make_settings
from tests.helpers import SEED_DIR, masuk, muat_persona

DIM = ["realistis", "investigatif", "artistik", "sosial", "enterprising", "konvensional"]
HEADER_PRODI = "prodi_id,rumpun,tag_minat,mapel_penentu,status,catatan\n"
HEADER_PROFESI = "rumpun,nama,deskripsi,status\n"


def tulis(folder: Path, prodi: str | None = None, profesi: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if prodi is not None:
        (folder / NAMA_PRODI).write_text(HEADER_PRODI + prodi, encoding="utf-8")
    if profesi is not None:
        (folder / NAMA_PROFESI).write_text(HEADER_PROFESI + profesi, encoding="utf-8")
    return folder


# ------------------------------------------------------------------ pemuatan (tanpa DB)


def test_folder_atau_berkas_tidak_ada_berarti_tidak_ada_draf(tmp_path):
    assert muat_draf(tmp_path / "tidak-ada", DIM).ada is False
    assert muat_draf(tulis(tmp_path / "kosong"), DIM).ada is False


def test_draf_valid_dimuat(tmp_path):
    f = tulis(
        tmp_path,
        f'ui-ilmu-komputer,TI,investigatif|realistis,matematika|informatika,"{LABEL_DRAF}",x\n',
        f'Teknologi Informasi,Analis data,,"{LABEL_DRAF}"\n',
    )
    d = muat_draf(f, DIM)
    assert d.ada and d.tag_minat == {"ui-ilmu-komputer": ["investigatif", "realistis"]}
    assert d.mapel == {"ui-ilmu-komputer": ["matematika", "informatika"]}
    assert d.profesi == {"Teknologi Informasi": ["Analis data"]}


@pytest.mark.parametrize(
    "prodi,pesan",
    [
        ("p1,TI,astronomi,matematika,draf,x\n", "bukan kode RIASEC"),
        ("p1,TI,investigatif,matematika,terverifikasi,x\n", "berlabel"),
        (",TI,investigatif,matematika,draf,x\n", "prodi_id kosong"),
    ],
)
def test_draf_tidak_valid_gagal_cepat(tmp_path, prodi, pesan):
    with pytest.raises(ConfigError, match=pesan):
        muat_draf(tulis(tmp_path, prodi), DIM)


def test_berkas_draf_tidak_boleh_memuat_kolom_verifikasi(tmp_path):
    (tmp_path / NAMA_PROFESI).write_text(
        "rumpun,nama,status,terakhir_diverifikasi\nTI,Analis,draf,2026-10-14\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="terakhir_diverifikasi"):
        muat_draf(tmp_path, DIM)


# ------------------------------------------------------------------ berkas draf di repo


def test_draf_di_repo_valid_terpisah_dari_seed_dan_sinkron_dengan_generator(app_config):
    draf_dir = ROOT_DIR / "data" / "draft"
    d = muat_draf(draf_dir, app_config.minat.dimensi)
    assert d.ada and d.profesi
    with (SEED_DIR / "prodi.csv").open(encoding="utf-8-sig", newline="") as f:
        id_seed = {r["prodi_id"] for r in csv.DictReader(f)}
    assert set(d.tag_minat) <= id_seed  # tidak ada prodi siluman
    for nama in (NAMA_PRODI, NAMA_PROFESI):
        assert not (SEED_DIR / nama).exists()  # tidak dicampur ke CSV utama
        kolom = (draf_dir / nama).read_text(encoding="utf-8").splitlines()[0]
        assert "diverifikasi" not in kolom  # tanggal verifikasi hanya diisi manusia
    assert generator.main(["--cek"]) == 0, "jalankan: python -m scripts.buat_draf_eksplorasi"


# ------------------------------------------------------------------ /explore


@pytest.fixture()
def buat_app(clean_db: Engine, app_config: AppConfig, tmp_path: Path):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))

    def _buat(draf_dir: Path | None):
        pengaturan = {"draf_dir": str(draf_dir)} if draf_dir else {}
        return TestClient(
            create_app(make_settings(**pengaturan), app_config, clean_db),
            raise_server_exceptions=False,
        )

    return _buat


def jelajah(c, h, **body):
    r = c.post("/api/v1/explore", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def draf_ti(tmp_path: Path) -> Path:
    baris = "".join(
        f'{pid},Teknologi Informasi,investigatif|realistis,matematika|informatika,"{LABEL_DRAF}",x\n'
        for pid in ("ui-ilmu-komputer", "ugm-ilmu-komputer")
    )
    return tulis(
        tmp_path / "draf", baris, f'Teknologi Informasi,Penguji perangkat lunak,,"{LABEL_DRAF}"\n'
    )


@pytest.mark.db
def test_hasil_dari_draf_ditandai(buat_app, tmp_path):
    with buat_app(draf_ti(tmp_path)) as c:
        h = muat_persona(c, "rani")
        d = jelajah(c, h, top_n=10)
        ti = next(r for r in d["rekomendasi"] if r["rumpun"] == "Teknologi Informasi")
        assert ti["sumber_profil"] == {"minat": "draf", "mapel": "draf", "profesi": "draf"}
        assert ti["label_data"] == LABEL_DRAF and ti["contoh_profesi"] == [
            "Penguji perangkat lunak"
        ]
        assert d["memakai_data_draf"] is True
        assert any("data draf, belum terverifikasi" in x for x in d["catatan"])
        lain = next(r for r in d["rekomendasi"] if r["rumpun"] == "Hukum")
        assert lain["label_data"] is None and lain["sumber_profil"]["minat"] == "klasifikasi_awal"


@pytest.mark.db
def test_tanpa_draf_memakai_klasifikasi_awal_tanpa_penanda_draf(buat_app):
    with buat_app(None) as c:  # default tes: folder draf tidak ada
        d = jelajah(c, muat_persona(c, "rani"), top_n=10)
        assert d["memakai_data_draf"] is False
        assert all(r["label_data"] is None for r in d["rekomendasi"])
        assert all("draf" not in r["sumber_profil"].values() for r in d["rekomendasi"])
        assert not any("data draf" in x for x in d["catatan"])


@pytest.mark.db
def test_data_resmi_didahulukan_dari_draf(buat_app, tmp_path, clean_db):
    with Session(clean_db) as db:
        db.get(m.Prodi, "ui-ilmu-komputer").tag_minat = ["investigatif"]
        db.commit()
    with buat_app(draf_ti(tmp_path)) as c:
        d = jelajah(c, muat_persona(c, "rani"), top_n=10)
        ti = next(r for r in d["rekomendasi"] if r["rumpun"] == "Teknologi Informasi")
        assert ti["sumber_profil"]["minat"] == "data"  # tabel prodi menang atas draf
        assert ti["sumber_profil"]["mapel"] == "draf"  # mapel resmi masih kosong


@pytest.mark.db
def test_draf_repo_dipakai_aplikasi_nyata_dan_ditandai(clean_db, app_config):
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    app = create_app(
        make_settings(draf_dir=str(ROOT_DIR / "data" / "draft")),
        app_config,
        clean_db,
    )
    with TestClient(app) as c:
        d = jelajah(c, muat_persona(c, "rani"), top_n=10)
        assert d["memakai_data_draf"] is True and d["rekomendasi"]
        assert all(r["label_data"] == LABEL_DRAF for r in d["rekomendasi"])


# ------------------------------------------------------------------ fallback penelusuran katalog


@pytest.mark.db
def test_tanpa_minat_dan_nilai_hanya_penelusuran_katalog_tanpa_skor(buat_app):
    with buat_app(None) as c:
        d = jelajah(c, masuk(c))
        assert d["rekomendasi"] == [] and {x["field"] for x in d["data_kurang"]} == {
            "minat",
            "nilai_rapor",
        }
        rumpun = {x["rumpun"] for x in d["penelusuran_katalog"]}
        assert len(rumpun) == 10 and "Teknologi Informasi" in rumpun
        for x in d["penelusuran_katalog"]:
            assert "skor_kecocokan" not in x and x["total_prodi"] >= 1 and x["prodi_ids"]
            assert x["ptn"] and set(x["ptn"][0]) == {"id", "nama", "provinsi", "prodi_ids"}
        assert any("penelusuran_katalog" in x for x in d["catatan"])


@pytest.mark.db
def test_penelusuran_katalog_kosong_bila_semua_rumpun_dinilai(buat_app):
    with buat_app(None) as c:
        d = jelajah(c, muat_persona(c, "rani"), top_n=3)
        assert d["penelusuran_katalog"] == []
        assert not any("penelusuran_katalog" in x for x in d["catatan"])
