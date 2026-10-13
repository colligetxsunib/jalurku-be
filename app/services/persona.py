"""Persona demo fiktif (config/personas/*.json): satu sumber kebenaran untuk skrip seed, tes golden,
ekspor halaman statis, dan tombol "Muat persona demo" di frontend (PRD bagian 13).

Aturan:
- Persona selalu fiktif (`fiktif: true`); data siswa nyata tidak boleh masuk ke sini.
- `harapan` adalah hasil yang diharapkan dari mesin aturan. Ia baru "terverifikasi" bila manusia
  sudah mencocokkannya dengan sumber resmi: `hasil_terverifikasi: true` mewajibkan
  `terakhir_diverifikasi` dan `diverifikasi_oleh`. Kode tidak pernah mengisinya sendiri.
- `harapan.penilaian` adalah cuplikan keluaran mesin (kunci regresi), bukan klaim kebenaran,
  sampai `hasil_terverifikasi` bernilai true.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import ROOT_DIR
from app.schemas.profile import ProfilePatch

PERSONA_DIR = ROOT_DIR / "config" / "personas"
Jalur = Literal["SNBP", "SNBT"]
StatusGate = Literal["lolos", "tidak_memenuhi_syarat", "data_kurang"]


class PersonaError(ValueError):
    """Berkas persona tidak valid."""


class Harapan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hasil_terverifikasi: bool = False
    terakhir_diverifikasi: date | None = None
    diverifikasi_oleh: str | None = None
    gate: dict[Jalur, StatusGate]
    # {jalur: {prodi_id: kategori}} untuk pilihan di `strategi_demo`. Cuplikan mesin, bukan klaim.
    penilaian: dict[Jalur, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _verifikasi_butuh_penanggung_jawab(self) -> Harapan:
        if self.hasil_terverifikasi and not (self.terakhir_diverifikasi and self.diverifikasi_oleh):
            raise ValueError(
                "hasil_terverifikasi=true wajib disertai terakhir_diverifikasi dan diverifikasi_oleh"
            )
        return self


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,30}$")
    nama: str
    fiktif: Literal[True]
    skenario: str
    deskripsi: str
    profil: dict[str, Any]
    target_prodi_ids: list[str] = Field(default_factory=list)
    # Pilihan untuk demo/ekspor statis: {jalur: [prodi_id, ...]}
    strategi_demo: dict[Jalur, list[str]] = Field(default_factory=dict)
    harapan: Harapan

    @model_validator(mode="after")
    def _profil_sesuai_skema(self) -> Persona:
        try:
            ProfilePatch.model_validate(self.profil)  # skema yang sama dengan PUT /profile
        except ValidationError as exc:
            e = exc.errors()[0]
            raise ValueError(
                f"profil tidak valid ({'.'.join(map(str, e['loc']))}: {e['msg']})"
            ) from exc
        for jalur in self.harapan.penilaian:
            if jalur not in self.strategi_demo:
                raise ValueError(f"harapan.penilaian.{jalur} tanpa strategi_demo.{jalur}")
        return self


def baca_persona(path: Path) -> Persona:
    try:
        isi = json.loads(path.read_text(encoding="utf-8"))
        persona = Persona.model_validate(isi)
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonaError(f"{path.name}: tidak bisa dibaca ({type(exc).__name__})") from exc
    except ValidationError as exc:
        e = exc.errors()[0]
        raise PersonaError(f"{path.name}: {'.'.join(map(str, e['loc']))}: {e['msg']}") from exc
    if persona.id != path.stem:
        raise PersonaError(f"{path.name}: id '{persona.id}' harus sama dengan nama berkas")
    return persona


def muat_semua(direktori: Path = PERSONA_DIR) -> list[Persona]:
    """Semua persona, urut nama berkas. Gagal pada berkas pertama yang tidak valid."""
    return [baca_persona(p) for p in sorted(direktori.glob("*.json"))]


def muat(nama: str, direktori: Path = PERSONA_DIR) -> Persona:
    if not nama.isidentifier() and not nama.replace("-", "_").isidentifier():
        raise PersonaError(f"nama persona tidak valid: {nama!r}")
    path = direktori / f"{nama}.json"
    if not path.is_file():
        tersedia = ", ".join(p.stem for p in sorted(direktori.glob("*.json")))
        raise PersonaError(f"persona '{nama}' tidak ditemukan (tersedia: {tersedia})")
    return baca_persona(path)
