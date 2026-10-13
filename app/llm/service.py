"""Layanan LLM: cache + pembatas konkurensi global + fallback. Titik masuk tunggal ke penyedia LLM.

Kuota Gemini berlaku per API key (bukan per sesi), jadi semua panggilan melewati satu semaphore.
Setiap kegagalan menghasilkan hasil `fallback=True` (BUKAN exception), sehingga endpoint tidak
mengembalikan 5xx hanya karena LLM mati (PRD 13, keandalan demo).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import AppConfig, Settings
from app.llm import cache
from app.llm.client import GeminiClient, LLMClient, NullClient
from app.llm.errors import LLMAntreanPenuh, LLMError, LLMGagal
from app.llm.pii import normalisasi_pertanyaan

log = logging.getLogger("jalurku.llm")
T = TypeVar("T")


@dataclass(frozen=True)
class HasilEmbed:
    vektor: list[float] | None
    fallback: bool
    dari_cache: bool = False
    alasan: str | None = None


@dataclass(frozen=True)
class HasilGenerate:
    teks: str | None
    fallback: bool
    dari_cache: bool = False
    alasan: str | None = None


def buat_client(settings: Settings, config: AppConfig) -> LLMClient:
    if not settings.gemini_api_key:
        return NullClient()
    return GeminiClient(
        settings.gemini_api_key,
        model=config.llm.model,
        embedding_model=config.embedding.model,
        dimensi=config.embedding.dimensi,
        timeout_detik=config.llm.timeout_detik,
    )


class LLMService:
    def __init__(
        self, client: LLMClient, config: AppConfig, *, tunggu_antrean_detik: float | None = None
    ) -> None:
        self._client = client
        self._config = config
        self._semaphore = threading.BoundedSemaphore(config.llm.maks_konkuren)
        self._tunggu = (
            config.llm.timeout_detik if tunggu_antrean_detik is None else tunggu_antrean_detik
        )

    @property
    def client(self) -> LLMClient:
        """Klien mentah, untuk ingest dokumen offline (embedding massal)."""
        return self._client

    @property
    def dikonfigurasi(self) -> bool:
        """False bila tidak ada kunci API: fitur opsional berbasis LLM dilewati tanpa panggilan."""
        return not isinstance(self._client, NullClient)

    # ------------------------------------------------------------------ util

    def _jalankan(self, operasi: str, fn: Callable[[], T]) -> T:
        if not self._semaphore.acquire(timeout=self._tunggu):
            raise LLMAntreanPenuh("antrean LLM penuh")
        try:
            return fn()
        finally:
            self._semaphore.release()

    @staticmethod
    def _alasan(exc: Exception) -> str:
        return type(exc).__name__

    # ------------------------------------------------------------------ embedding

    def embed_pertanyaan(self, db: Session, pertanyaan_bersih: str) -> HasilEmbed:
        """Satu panggilan embedding per pertanyaan, di-cache per pertanyaan ternormalisasi.

        Argumen WAJIB sudah melewati penyaring PII. task_type = RETRIEVAL_QUERY.
        """
        cfg = self._config
        kunci = cache.buat_kunci(
            "embed_query",
            f"{cfg.embedding.model}:{cfg.embedding.dimensi}",
            normalisasi_pertanyaan(pertanyaan_bersih),
        )
        tersimpan = cache.ambil(db, kunci)
        if tersimpan is not None:
            return HasilEmbed(tersimpan["vektor"], fallback=False, dari_cache=True)
        try:
            vektor = self._jalankan(
                "embed",
                lambda: self._client.embed([pertanyaan_bersih], task_type="RETRIEVAL_QUERY")[0],
            )
        except LLMError as exc:
            log.warning("embedding gagal (%s)", self._alasan(exc))
            return HasilEmbed(None, fallback=True, alasan=self._alasan(exc))
        cache.simpan(db, kunci, {"vektor": vektor}, cfg.llm.cache_ttl_detik)
        return HasilEmbed(vektor, fallback=False)

    # ------------------------------------------------------------------ generate

    def generate(
        self,
        db: Session,
        *,
        namespace: str,
        system: str,
        prompt: str,
        kunci_cache: Mapping[str, Any],
        json_schema: type[BaseModel] | None = None,
        max_output_tokens: int = 1024,
        izin: Callable[[], bool] | None = None,
    ) -> HasilGenerate:
        """`kunci_cache` = masukan deterministik BEBAS PII yang menentukan keluaran (mis. fakta mesin aturan).

        `izin` dipanggil hanya bila cache meleset, tepat sebelum panggilan nyata ke penyedia
        (mis. untuk menghitung batas per sesi). False berarti jangan memanggil: hasil fallback.
        """
        cfg = self._config
        kunci = cache.buat_kunci(namespace, cfg.llm.model, kunci_cache)
        tersimpan = cache.ambil(db, kunci)
        if tersimpan is not None:
            return HasilGenerate(tersimpan["teks"], fallback=False, dari_cache=True)
        if izin is not None and not izin():
            return HasilGenerate(None, fallback=True, alasan="BatasSesi")
        try:
            teks = self._jalankan(
                "generate",
                lambda: self._client.generate(
                    prompt,
                    system=system,
                    json_schema=json_schema,
                    max_output_tokens=max_output_tokens,
                ),
            )
        except LLMError as exc:
            log.warning("generate gagal (%s)", self._alasan(exc))
            return HasilGenerate(None, fallback=True, alasan=self._alasan(exc))
        except Exception as exc:  # klien palsu/lainnya: jangan jatuhkan permintaan
            log.warning("generate gagal tak terduga (%s)", type(exc).__name__)
            return HasilGenerate(None, fallback=True, alasan=LLMGagal.__name__)
        cache.simpan(db, kunci, {"teks": teks}, cfg.llm.cache_ttl_detik)
        return HasilGenerate(teks, fallback=False)
