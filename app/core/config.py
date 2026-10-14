"""Konfigurasi aplikasi: env (rahasia, koneksi) + config/app.yaml (nilai yang bisa dikalibrasi).

Semua validasi dilakukan saat start (fail-fast), bukan saat request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "app.yaml"


class ConfigError(RuntimeError):
    """Konfigurasi tidak valid. Aplikasi tidak boleh start."""


class Settings(BaseSettings):
    """Nilai dari environment variable / berkas .env. Tidak boleh masuk repositori."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    database_url: str = "postgresql+psycopg://jalurku:jalurku@127.0.0.1:5433/jalurku"
    gemini_api_key: str = ""
    admin_key: str = ""
    cors_origins: str = ""
    # IP/CIDR reverse proxy (nginx) yang boleh menyetel X-Forwarded-For; menimpa rate_limit.proxy_tepercaya
    trusted_proxies: str = ""
    session_ttl_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    require_verified: bool = False
    app_env: Literal["dev", "prod"] = "dev"
    app_config_path: str = str(DEFAULT_CONFIG_PATH)
    seed_dir: str = str(ROOT_DIR / "data" / "seed")
    dokumen_dir: str = str(ROOT_DIR / "data" / "dokumen")

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxies_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Batas(_Strict):
    maks: int = Field(gt=0)
    jendela_detik: int = Field(gt=0)


class SesiConfig(_Strict):
    ttl_jam: int = Field(default=24, ge=1)
    interval_pembersihan_menit: int = Field(default=10, ge=1)


class RateLimitConfig(_Strict):
    per_sesi: Batas
    per_ip: Batas
    buat_sesi_per_ip: Batas
    llm_per_sesi: Batas
    proxy_tepercaya: list[str] = Field(default_factory=list)

    @field_validator("proxy_tepercaya")
    @classmethod
    def _cek_proxy(cls, v: list[str]) -> list[str]:
        import ipaddress

        for item in v:
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(f"alamat/CIDR tidak valid: {item}") from exc
        return v


class LLMConfig(_Strict):
    model: str = Field(min_length=1)
    timeout_detik: float = Field(gt=0)
    maks_konkuren: int = Field(ge=1)
    cache_ttl_detik: int = Field(ge=0)


class EmbeddingConfig(_Strict):
    model: str = Field(min_length=1)
    dimensi: int = Field(gt=0)


class RagConfig(_Strict):
    ukuran_chunk_min: int = Field(gt=0)
    ukuran_chunk_maks: int = Field(gt=0)
    overlap_chunk: int = Field(ge=0)
    maks_token_chunk: int = Field(gt=0)
    ukuran_batch_embedding: int = Field(ge=1, le=100)
    top_k: int = Field(ge=1)
    ambang_skor: float = Field(ge=0, le=1)
    saran_pertanyaan: list[str] = Field(default_factory=list)


class MinatConfig(_Strict):
    dimensi: list[str] = Field(min_length=1)


class RiasecItem(_Strict):
    """Satu pernyataan aktivitas tes minat. `id` stabil, `dimensi` harus anggota minat.dimensi."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    dimensi: str = Field(min_length=1)
    teks: str = Field(min_length=1, max_length=300)


class RiasecSkala(_Strict):
    """Skala Likert jawaban (inklusif). Label hanya untuk tampilan frontend."""

    min: int = Field(default=0)
    maks: int = Field(default=4)
    label: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _urut(self) -> RiasecSkala:
        if self.min >= self.maks:
            raise ValueError("skala.min harus lebih kecil dari skala.maks")
        return self


class RiasecConfig(_Strict):
    """Instrumen tes minat RIASEC (PRD 8.3, FR-E2). Item dari O*NET IP (domain publik), adaptasi ID."""

    aktif: bool = True
    versi_instrumen: str = Field(min_length=1, max_length=64)
    sumber: str = Field(default="", max_length=300)
    min_terjawab: int = Field(default=0, ge=0)  # 0 = boleh parsial
    skala: RiasecSkala = Field(default_factory=RiasecSkala)
    item: list[RiasecItem] = Field(min_length=1)


class ProfilConfig(_Strict):
    tahun_lulus_mundur: int = Field(ge=0)
    tahun_lulus_maju: int = Field(ge=0)
    skor_tryout_min: float
    skor_tryout_maks: float
    paket_c_usia_min: int = Field(ge=0)
    paket_c_usia_maks: int = Field(gt=0)

    @model_validator(mode="after")
    def _rentang(self) -> ProfilConfig:
        if self.skor_tryout_min >= self.skor_tryout_maks:
            raise ValueError("skor_tryout_min harus lebih kecil dari skor_tryout_maks")
        if self.paket_c_usia_min >= self.paket_c_usia_maks:
            raise ValueError("paket_c_usia_min harus lebih kecil dari paket_c_usia_maks")
        return self


KategoriNilai = Literal["safe", "match", "reach"]


class BobotTier(_Strict):
    rapor: float = Field(ge=0)
    tren: float = Field(ge=0)
    peringkat: float = Field(ge=0)

    @model_validator(mode="after")
    def _jumlah_positif(self) -> BobotTier:
        if self.rapor + self.tren + self.peringkat <= 0:
            raise ValueError("jumlah bobot harus lebih dari 0")
        return self


class BatasTier(_Strict):
    lemah_sedang: float = Field(gt=0, le=1)
    sedang_kuat: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _urut(self) -> BatasTier:
        if self.lemah_sedang >= self.sedang_kuat:
            raise ValueError("lemah_sedang harus lebih kecil dari sedang_kuat")
        return self


class TrenConfig(_Strict):
    skala_poin: float = Field(gt=0)


class TierSiswaConfig(_Strict):
    bobot: BobotTier
    batas: BatasTier
    tren: TrenConfig


class BatasPita(_Strict):
    rendah_sedang: float = Field(gt=0)
    sedang_tinggi: float = Field(gt=0)

    @model_validator(mode="after")
    def _urut(self) -> BatasPita:
        if self.rendah_sedang >= self.sedang_tinggi:
            raise ValueError("rendah_sedang harus lebih kecil dari sedang_tinggi")
        return self


class PersentilPita(_Strict):
    rendah_sedang: float = Field(gt=0, lt=100)
    sedang_tinggi: float = Field(gt=0, lt=100)

    @model_validator(mode="after")
    def _urut(self) -> PersentilPita:
        if self.rendah_sedang >= self.sedang_tinggi:
            raise ValueError("persentil rendah_sedang harus lebih kecil dari sedang_tinggi")
        return self


class PitaConfig(_Strict):
    metode: Literal["tetap", "persentil"]
    batas: BatasPita
    persentil: PersentilPita
    min_sampel: int = Field(ge=2)
    kelompok: Literal["semua", "program"]


class SelMatriks(_Strict):
    kategori: KategoriNilai
    catatan: str | None = None


class BarisMatriks(_Strict):
    rendah: SelMatriks
    sedang: SelMatriks
    tinggi: SelMatriks


class MatriksConfig(_Strict):
    """Ke-9 sel wajib ada. Sel kosong atau kategori di luar {safe, match, reach} = gagal start."""

    lemah: BarisMatriks
    sedang: BarisMatriks
    kuat: BarisMatriks


class BatasSkor(_Strict):
    lemah_sedang: float
    sedang_kuat: float

    @model_validator(mode="after")
    def _urut(self) -> BatasSkor:
        if self.lemah_sedang >= self.sedang_kuat:
            raise ValueError("lemah_sedang harus lebih kecil dari sedang_kuat")
        return self


class SkalaSkorTryoutConfig(_Strict):
    """Bila ada, tier siswa SNBT dihitung dari skor tryout (bukan proksi rapor)."""

    batas: BatasSkor


class JalurPenilaianConfig(_Strict):
    tier_siswa: TierSiswaConfig
    pita_keketatan: PitaConfig
    matriks: MatriksConfig
    skala_skor_tryout: SkalaSkorTryoutConfig | None = None


class StrategiConfig(_Strict):
    min_pilihan_untuk_evaluasi: int = Field(ge=1)
    min_safe: int = Field(ge=0)
    maks_rasio_reach: float = Field(ge=0, le=1)
    peringatan_satu_ptn: bool
    peringatan_satu_jalur: bool
    maks_saran_swap: int = Field(ge=0)


class QueryConfig(_Strict):
    maks_saran_pertanyaan: int = Field(ge=0, le=10)
    pola_keputusan: list[str] = Field(min_length=1)
    pengecualian_keputusan: list[str] = Field(default_factory=list)

    @field_validator("pola_keputusan")
    @classmethod
    def _regex_valid(cls, v: list[str]) -> list[str]:
        import re

        for pola in v:
            try:
                re.compile(pola)
            except re.error as exc:
                raise ValueError(f"regex tidak valid '{pola}': {exc}") from exc
        return v


class TeksConfig(_Strict):
    catatan_sel: dict[str, str] = Field(default_factory=dict)


class ExploreBobot(_Strict):
    minat: float = Field(ge=0)
    nilai: float = Field(ge=0)


class ExploreRumpun(_Strict):
    """Klasifikasi awal satu rumpun. Dipakai hanya bila data (tag_minat, mapel_penentu, profesi) kosong."""

    minat: dict[str, float] = Field(default_factory=dict)  # dimensi minat -> bobot 0..1
    mapel: dict[str, float] = Field(default_factory=dict)  # mapel rapor -> bobot > 0
    profesi: list[str] = Field(default_factory=list)  # contoh umum

    @field_validator("minat")
    @classmethod
    def _minat_0_1(cls, v: dict[str, float]) -> dict[str, float]:
        salah = [d for d, b in v.items() if not 0 <= b <= 1]
        if salah:
            raise ValueError(f"bobot minat harus 0..1: {', '.join(salah)}")
        return v

    @field_validator("mapel")
    @classmethod
    def _mapel_positif(cls, v: dict[str, float]) -> dict[str, float]:
        salah = [d for d, b in v.items() if b <= 0]
        if salah:
            raise ValueError(f"bobot mapel harus > 0: {', '.join(salah)}")
        return v


class ExploreConfig(_Strict):
    top_n_default: int = Field(ge=1, le=20)
    top_n_maks: int = Field(ge=1, le=20)
    bobot: ExploreBobot
    maks_prodi_per_rumpun: int = Field(ge=1)  # daftar prodi_ids per rekomendasi (FR-E3)
    maks_prodi_kelayakan: int = Field(ge=1)  # prodi yang dinilai per rumpun saat jalur diminta
    maks_profesi: int = Field(ge=1, le=10)
    rumpun: dict[str, ExploreRumpun]

    @model_validator(mode="after")
    def _konsisten(self) -> ExploreConfig:
        if self.top_n_default > self.top_n_maks:
            raise ValueError("top_n_default tidak boleh melebihi top_n_maks")
        if self.bobot.minat + self.bobot.nilai <= 0:
            raise ValueError("bobot.minat + bobot.nilai harus > 0")
        return self


class AppConfig(_Strict):
    versi_config: int
    sesi: SesiConfig
    rate_limit: RateLimitConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    rag: RagConfig
    minat: MinatConfig
    riasec: RiasecConfig
    profil: ProfilConfig
    snbp: JalurPenilaianConfig
    snbt: JalurPenilaianConfig
    strategi: StrategiConfig
    query: QueryConfig
    teks: TeksConfig
    explore: ExploreConfig

    @model_validator(mode="after")
    def _dimensi_explore_dikenal(self) -> AppConfig:
        dikenal = set(self.minat.dimensi)
        for nama, r in self.explore.rumpun.items():
            asing = sorted(set(r.minat) - dikenal)
            if asing:
                raise ValueError(
                    f"explore.rumpun.{nama}.minat memakai dimensi tak dikenal: {', '.join(asing)}"
                )
        return self

    @model_validator(mode="after")
    def _instrumen_riasec_konsisten(self) -> AppConfig:
        """Instrumen RIASEC harus memakai dimensi yang dikenal dan menutup semua dimensi."""
        from app.domain.riasec import ItemRiasec, validasi_instrumen

        item = [ItemRiasec(id=i.id, dimensi=i.dimensi, teks=i.teks) for i in self.riasec.item]
        galat = validasi_instrumen(item, self.minat.dimensi)
        if galat:
            raise ValueError("instrumen riasec tidak konsisten: " + "; ".join(galat))
        return self

    def penilaian(self, jalur: str) -> JalurPenilaianConfig:
        return self.snbp if jalur == "SNBP" else self.snbt


def load_app_config(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"Berkas konfigurasi tidak ditemukan: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML tidak valid di {p}: {exc}") from exc
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        pesan = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"Konfigurasi tidak valid di {p}: {pesan}") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_app_config() -> AppConfig:
    return load_app_config(get_settings().app_config_path)
