"""Task 17: berkas persona demo (config/personas) valid, fiktif, dan konsisten dengan data seed."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services import persona as modul
from app.services.persona import Persona, PersonaError
from tests.helpers import SEED_DIR

DASAR = {
    "id": "uji",
    "nama": "Uji (persona fiktif)",
    "fiktif": True,
    "skenario": "A",
    "deskripsi": "Persona untuk tes.",
    "profil": {"tahun_lulus": 2026, "provinsi": "Jawa Barat"},
    "strategi_demo": {"SNBT": ["ui-ilmu-komputer"]},
    "harapan": {"gate": {"SNBT": "lolos"}, "penilaian": {"SNBT": {"ui-ilmu-komputer": "match"}}},
}


def varian(**ubah) -> dict:
    d = copy.deepcopy(DASAR)
    for kunci, nilai in ubah.items():
        d[kunci] = nilai
    return d


def id_prodi_seed() -> set[str]:
    with (SEED_DIR / "prodi.csv").open(encoding="utf-8", newline="") as f:
        return {r["prodi_id"] for r in csv.DictReader(f)}


def test_semua_berkas_persona_valid():
    daftar = modul.muat_semua()
    assert {p.id for p in daftar} == {"rani", "dimas", "budi", "sinta"}
    assert all(p.fiktif is True for p in daftar)


def test_pilihan_demo_dan_target_ada_di_katalog_seed():
    ada = id_prodi_seed()
    for p in modul.muat_semua():
        ids = set(p.target_prodi_ids) | {i for daftar in p.strategi_demo.values() for i in daftar}
        assert ids <= ada, (p.id, sorted(ids - ada))
        for jalur, peta in p.harapan.penilaian.items():
            assert set(peta) == set(p.strategi_demo[jalur]), (p.id, jalur)


def test_harapan_gate_mencakup_dua_jalur_untuk_persona_demo():
    for p in modul.muat_semua():
        assert set(p.harapan.gate) == {"SNBP", "SNBT"}, p.id


def test_tidak_ada_persona_yang_ditandai_terverifikasi_otomatis():
    """Verifikasi hanya oleh manusia: berkas yang dikirim tidak boleh sudah bertanda terverifikasi
    tanpa penanggung jawab. (Bila tim sudah memverifikasi, penanggung jawabnya wajib terisi.)"""
    for p in modul.muat_semua():
        h = p.harapan
        assert (not h.hasil_terverifikasi) or (h.diverifikasi_oleh and h.terakhir_diverifikasi)


def test_persona_wajib_fiktif():
    with pytest.raises(ValidationError):
        Persona.model_validate(varian(fiktif=False))
    d = varian()
    del d["fiktif"]
    with pytest.raises(ValidationError):
        Persona.model_validate(d)


def test_terverifikasi_wajib_punya_penanggung_jawab_dan_tanggal():
    harapan = {**DASAR["harapan"], "hasil_terverifikasi": True}
    with pytest.raises(ValidationError, match="diverifikasi_oleh"):
        Persona.model_validate(varian(harapan=harapan))
    harapan |= {"terakhir_diverifikasi": "2026-10-14", "diverifikasi_oleh": "Tim Data"}
    assert Persona.model_validate(varian(harapan=harapan)).harapan.hasil_terverifikasi is True


@pytest.mark.parametrize(
    "profil",
    [
        {"nama_lengkap": "Rani"},  # identitas tidak boleh ada di profil (FR-P4)
        {"nik": "3201xxxxxxxxxxxx"},
        {"provinsi": "Atlantis"},
        {"tahun_lulus": "dua ribu"},
    ],
)
def test_profil_harus_lolos_skema_put_profile(profil):
    with pytest.raises(ValidationError, match="profil"):
        Persona.model_validate(varian(profil=profil))


def test_harapan_penilaian_butuh_strategi_demo():
    with pytest.raises(ValidationError, match="strategi_demo"):
        Persona.model_validate(varian(strategi_demo={}))


def test_kunci_tak_dikenal_ditolak():
    with pytest.raises(ValidationError):
        Persona.model_validate(varian(umur=17))


def test_id_harus_sama_dengan_nama_berkas(tmp_path: Path):
    (tmp_path / "lain.json").write_text(json.dumps(DASAR), encoding="utf-8")
    with pytest.raises(PersonaError, match="harus sama dengan nama berkas"):
        modul.baca_persona(tmp_path / "lain.json")


def test_berkas_rusak_dilaporkan_dengan_nama_berkas(tmp_path: Path):
    (tmp_path / "uji.json").write_text("{bukan json", encoding="utf-8")
    with pytest.raises(PersonaError, match=r"uji\.json"):
        modul.baca_persona(tmp_path / "uji.json")


def test_muat_menolak_nama_berbahaya_dan_menyebut_yang_tersedia():
    for nama in ("../config", "a/b", "..\\x", ""):
        with pytest.raises(PersonaError):
            modul.muat(nama)
    with pytest.raises(PersonaError, match="rani"):
        modul.muat("tidak-ada")
