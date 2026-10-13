"""Klien Gemini (google-genai). Satu-satunya modul yang memanggil jaringan LLM.

`domain/` TIDAK boleh meng-import modul ini (PRD 8.5); ada tes yang menjaganya.
Pesan error tidak pernah memuat isi prompt/pertanyaan atau kunci API.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from app.llm.errors import (
    LLMGagal,
    LLMKuotaHabis,
    LLMTidakDikonfigurasi,
    LLMTimeout,
)


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
        sdk_client: Any | None = None,
    ) -> None:
        self._model = model
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
        try:
            res = self._client.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        except Exception as exc:
            raise petakan_error(exc) from None
        teks = (res.text or "").strip()
        if not teks:
            raise LLMGagal("respons LLM kosong")
        return teks
