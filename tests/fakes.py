"""Klien LLM palsu untuk tes: tanpa jaringan, bisa dipantau, bisa dibuat gagal."""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections.abc import Sequence
from typing import Any

from app.llm.client import l2_normalisasi


def vektor_dari_teks(teks: str, dimensi: int = 768) -> list[float]:
    """Vektor deterministik (L2) dari teks: teks sama -> vektor sama."""
    rng = random.Random(int.from_bytes(hashlib.sha256(teks.encode()).digest()[:8], "big"))
    return l2_normalisasi([rng.uniform(-1, 1) for _ in range(dimensi)])


class FakeLLM:
    def __init__(
        self,
        *,
        dimensi: int = 768,
        teks: str = "Jawaban uji.",
        gagal: Exception | None = None,
        gagal_embed: Exception | None = None,
        jeda: float = 0.0,
        peta_embed: dict[str, list[float]] | None = None,
        balasan: Any = None,
    ) -> None:
        self.dimensi = dimensi
        self.teks = teks
        self.gagal = gagal
        self.gagal_embed = gagal_embed
        self.jeda = jeda
        self.peta_embed = peta_embed or {}
        self.balasan = balasan  # callable(prompt, system, json_schema) -> str
        self.panggilan_embed = 0
        self.panggilan_generate = 0
        self.task_types: list[str] = []
        self.prompt_terakhir: str | None = None
        self.system_terakhir: str | None = None
        self.embed_teks: list[str] = []
        self._kunci = threading.Lock()
        self.aktif = 0
        self.aktif_maks = 0

    def embed(self, teks: Sequence[str], *, task_type: str) -> list[list[float]]:
        self.panggilan_embed += 1
        self.task_types.append(task_type)
        self.embed_teks.extend(teks)
        if self.gagal_embed:
            raise self.gagal_embed
        return [self.peta_embed.get(t) or vektor_dari_teks(t, self.dimensi) for t in teks]

    def generate(self, prompt: str, *, system=None, json_schema=None, **_: Any) -> str:
        with self._kunci:
            self.panggilan_generate += 1
            self.aktif += 1
            self.aktif_maks = max(self.aktif_maks, self.aktif)
        try:
            self.prompt_terakhir, self.system_terakhir = prompt, system
            if self.jeda:
                time.sleep(self.jeda)
            if self.gagal:
                raise self.gagal
            if self.balasan is not None:
                return self.balasan(prompt, system, json_schema)
            return self.teks
        finally:
            with self._kunci:
                self.aktif -= 1
