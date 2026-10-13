"""Hierarki error LLM. Pesan TIDAK boleh memuat isi pertanyaan, prompt, atau kunci API."""

from __future__ import annotations


class LLMError(Exception):
    """Dasar. Semua turunan berarti: pakai teks cadangan (fallback), jangan melempar 5xx ke siswa."""


class LLMTidakDikonfigurasi(LLMError):
    """GEMINI_API_KEY belum diisi."""


class LLMKuotaHabis(LLMError):
    """HTTP 429 dari penyedia (batas permintaan per menit/hari)."""


class LLMTimeout(LLMError):
    pass


class LLMAntreanPenuh(LLMError):
    """Pembatas konkurensi global penuh dan waktu tunggu habis."""


class LLMGagal(LLMError):
    """Kegagalan lain (kredensial, 5xx, respons kosong/tidak sesuai)."""
