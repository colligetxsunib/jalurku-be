"""Klien Gemini (google-genai). Satu-satunya modul yang memanggil jaringan LLM.

`domain/` TIDAK boleh meng-import modul ini (PRD 8.5); ada tes yang menjaganya.
Pesan error tidak pernah memuat isi prompt/pertanyaan atau kunci API.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.llm.errors import (
    LLMGagal,
    LLMKuotaHabis,
    LLMModelTidakAda,
    LLMTidakDikonfigurasi,
    LLMTimeout,
)

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    def embed(self, teks: Sequence[str], *, task_type: str) -> list[list[float]]: ...

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: type[BaseModel] | None = None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str: ...


def l2_normalisasi(v: Sequence[float]) -> list[float]:
    """Model embedding tidak menormalisasi dimensi selain 3072, jadi dilakukan di sisi aplikasi."""
    norma = math.sqrt(sum(x * x for x in v))
    if norma == 0:
        raise LLMGagal("vektor embedding bernorma nol")
    return [x / norma for x in v]


class NullClient:
    """Dipakai bila GEMINI_API_KEY kosong: semua panggilan langsung memicu fallback."""

    def embed(self, teks: Sequence[str], *, task_type: str) -> list[list[float]]:
        raise LLMTidakDikonfigurasi("GEMINI_API_KEY belum diisi")

    def generate(self, prompt: str, **_: Any) -> str:
        raise LLMTidakDikonfigurasi("GEMINI_API_KEY belum diisi")


def petakan_error(exc: Exception) -> Exception:
    """Petakan error SDK/HTTP ke hierarki sendiri tanpa membawa isi permintaan."""
    from google.genai import errors

    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return LLMTimeout("timeout memanggil penyedia LLM")
    if isinstance(exc, errors.APIError):
        kode = getattr(exc, "code", None)
        if kode == 429:
            return LLMKuotaHabis("batas permintaan penyedia LLM terlampaui (429)")
        if kode == 404:
            return LLMModelTidakAda("model tidak ditemukan di penyedia LLM (404)")
        if kode in (408, 504):
            return LLMTimeout(f"timeout dari penyedia LLM ({kode})")
        return LLMGagal(f"penyedia LLM mengembalikan error {kode}")
    return LLMGagal(f"panggilan LLM gagal: {type(exc).__name__}")


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        embedding_model: str,
        dimensi: int,
        timeout_detik: float,
        model_cadangan: Sequence[str] = (),
        sdk_client: Any | None = None,
    ) -> None:
        self._model = model
        # Urutan percobaan generate: utama lalu cadangan (tanpa duplikat).
        self._urutan_model = [model, *[n for n in dict.fromkeys(model_cadangan) if n != model]]
        self._model_tidak_ada: set[str] = set()  # 404 bersifat permanen selama proses berjalan
        self._embedding_model = embedding_model
        self._dimensi = dimensi
        if sdk_client is not None:
            self._client = sdk_client
        else:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=int(timeout_detik * 1000)),  # milidetik
            )

    def embed(self, teks: Sequence[str], *, task_type: str) -> list[list[float]]:
        from google.genai import types

        try:
            res = self._client.models.embed_content(
                model=self._embedding_model,
                contents=list(teks),
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=self._dimensi
                ),
            )
        except Exception as exc:
            raise petakan_error(exc) from None
        vektor = [l2_normalisasi(list(e.values)) for e in (res.embeddings or [])]
        if len(vektor) != len(teks) or any(len(v) != self._dimensi for v in vektor):
            raise LLMGagal(f"embedding tidak sesuai (harus {self._dimensi} dimensi)")
        return vektor

    def _generate_dengan_cadangan(self, prompt: str, config: Any) -> Any:
        """Coba model utama, lalu cadangan, hanya untuk 404 (model hilang) dan 429 (kuota).

        Error lain (timeout, 5xx, kredensial) langsung dilempar: model lain tidak menolongnya.
        Bila semua model gagal, error terakhir dilempar dan pemanggil jatuh ke teks template.
        """
        terakhir: Exception | None = None
        for nama in self._urutan_model:
            if nama in self._model_tidak_ada:
                continue
            try:
                res = self._client.models.generate_content(
                    model=nama, contents=prompt, config=config
                )
            except Exception as exc:
                dipetakan = petakan_error(exc)
                if isinstance(dipetakan, LLMModelTidakAda):
                    self._model_tidak_ada.add(nama)
                    log.warning("model generate tidak ditemukan (404): %s", nama)
                elif isinstance(dipetakan, LLMKuotaHabis):
                    log.warning("kuota model generate habis (429): %s", nama)
                else:
                    raise dipetakan from None
                terakhir = dipetakan
                continue
            if nama != self._model:
                log.info("generate dijawab model cadangan: %s", nama)
            return res
        raise (terakhir or LLMModelTidakAda("semua model generate tidak tersedia (404)")) from None

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: type[BaseModel] | None = None,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json" if json_schema else None,
            response_schema=json_schema,
        )
        res = self._generate_dengan_cadangan(prompt, config)
        teks = (res.text or "").strip()
        if not teks:
            raise LLMGagal("respons LLM kosong")
        return teks
