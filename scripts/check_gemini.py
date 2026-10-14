"""Smoke test Gemini API: embedding (768 dimensi, L2) dan generate.

Dipakai hari 1 untuk memastikan model tersedia (PRD bagian 17 #7). Kuota per model hanya terlihat
di Google AI Studio, jadi cek di sana juga.

    uv run python -m scripts.check_gemini

Nama model dibaca dari LLM_MODEL, LLM_MODEL_FALLBACK, dan EMBED_MODEL di .env (bila kosong,
dari config/app.yaml). Daftar nama yang valid: uv run python -m scripts.list_models
"""

from __future__ import annotations

import math
import sys

from app.core.config import get_app_config, get_settings


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def main() -> int:
    settings = get_settings()
    cfg = get_app_config()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY belum diisi (.env). Buat kunci di Google AI Studio.", file=sys.stderr)
        return 2

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    gagal = 0

    print(f"Embedding: model={cfg.embedding.model} dimensi={cfg.embedding.dimensi}")
    try:
        res = client.models.embed_content(
            model=cfg.embedding.model,
            contents=["Berapa jumlah pilihan program studi di SNBP?"],
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY", output_dimensionality=cfg.embedding.dimensi
            ),
        )
        vec = list(res.embeddings[0].values)
        print(
            f"  OK dimensi={len(vec)} norma_mentah={_norm(vec):.4f} (harus dinormalisasi L2 manual)"
        )
        if len(vec) != cfg.embedding.dimensi:
            print("  GAGAL: dimensi tidak sesuai config", file=sys.stderr)
            gagal += 1
    except Exception as exc:  # noqa: BLE001 - skrip diagnosis, tampilkan jenis error saja
        print(f"  GAGAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        gagal += 1

    # Utama wajib berhasil; cadangan hanya diperiksa (gagal = peringatan, bukan kegagalan).
    for urut, nama in enumerate([cfg.llm.model, *settings.llm_model_fallback_list]):
        label = "utama" if urut == 0 else "cadangan"
        print(f"Generate ({label}): model={nama}")
        try:
            res = client.models.generate_content(
                model=nama, contents="Jawab satu kalimat: apa kepanjangan SNBP?"
            )
            print(f"  OK: {(res.text or '').strip()[:200]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  GAGAL: {type(exc).__name__}: {exc}", file=sys.stderr)
            if urut == 0:
                gagal += 1
    if gagal:
        print("Cari nama model yang tersedia: uv run python -m scripts.list_models")

    print("Selesai. Cek batas permintaan (RPM/RPD) kedua model di Google AI Studio.")
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
