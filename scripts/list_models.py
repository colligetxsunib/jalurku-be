"""Cetak model Gemini yang tersedia untuk kunci API ini (models.list).

Dipakai saat nama model di .env perlu dicari atau diganti (mis. model lama dihentikan dan
panggilan gagal 404). Menampilkan model yang mendukung generateContent dan embedContent;
salin namanya (tanpa awalan `models/`) ke LLM_MODEL, LLM_MODEL_FALLBACK, atau EMBED_MODEL di .env.

    uv run python -m scripts.list_models
    uv run python -m scripts.list_models --semua      # termasuk model yang tidak mendukung keduanya
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from typing import Any

from app.core.config import get_app_config, get_settings

GENERATE = "generateContent"
EMBED = "embedContent"


def _nama_pendek(nama: str | None) -> str:
    return (nama or "").removeprefix("models/")


def kelompokkan(models: Iterable[Any]) -> tuple[list[Any], list[Any]]:
    """Pisahkan model berdasarkan supported_actions: (generateContent, embedContent)."""
    gen: list[Any] = []
    emb: list[Any] = []
    for m in models:
        aksi = set(getattr(m, "supported_actions", None) or [])
        if GENERATE in aksi:
            gen.append(m)
        if EMBED in aksi:
            emb.append(m)
    gen.sort(key=lambda m: _nama_pendek(m.name))
    emb.sort(key=lambda m: _nama_pendek(m.name))
    return gen, emb


def _cetak(judul: str, daftar: list[Any], dipakai: dict[str, str]) -> None:
    print(f"\n{judul} ({len(daftar)})")
    if not daftar:
        print("  (tidak ada)")
    for m in daftar:
        nama = _nama_pendek(m.name)
        tanda = f"  <- {dipakai[nama]}" if nama in dipakai else ""
        batas = getattr(m, "input_token_limit", None)
        info = f" masukan={batas}" if batas else ""
        print(f"  {nama}{info}{tanda}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--semua", action="store_true", help="tampilkan juga model tanpa aksi di atas")
    args = ap.parse_args(argv)

    settings = get_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY belum diisi (.env). Buat kunci di Google AI Studio.", file=sys.stderr)
        return 2

    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        semua = list(client.models.list())
    except Exception as exc:  # noqa: BLE001 - skrip diagnosis, tampilkan jenis error saja
        print(f"GAGAL memanggil models.list: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    cfg = get_app_config()
    dipakai: dict[str, str] = {_nama_pendek(cfg.llm.model): "LLM_MODEL (aktif)"}
    for n in settings.llm_model_fallback_list:
        dipakai.setdefault(_nama_pendek(n), "LLM_MODEL_FALLBACK")
    dipakai.setdefault(_nama_pendek(cfg.embedding.model), "EMBED_MODEL (aktif)")

    gen, emb = kelompokkan(semua)
    print(f"Total model dari models.list: {len(semua)}")
    _cetak("Mendukung generateContent (untuk LLM_MODEL / LLM_MODEL_FALLBACK)", gen, dipakai)
    _cetak("Mendukung embedContent (untuk EMBED_MODEL)", emb, dipakai)

    if args.semua:
        lain = [m for m in semua if m not in gen and m not in emb]
        _cetak("Model lain", sorted(lain, key=lambda m: _nama_pendek(m.name)), dipakai)

    tersedia = {_nama_pendek(m.name) for m in semua}
    hilang = [
        f"{label}={nama}"
        for label, nama in (
            ("LLM_MODEL", _nama_pendek(cfg.llm.model)),
            *(("LLM_MODEL_FALLBACK", _nama_pendek(n)) for n in settings.llm_model_fallback_list),
            ("EMBED_MODEL", _nama_pendek(cfg.embedding.model)),
        )
        if nama not in tersedia
    ]
    if hilang:
        print("\nPERINGATAN, tidak ada di models.list untuk kunci ini: " + ", ".join(hilang))
    print(
        "\nCatatan: EMBED_MODEL dikunci bersama dimensi kolom vektor (768). Mengganti model embedding "
        "berarti re-embed semua chunk dokumen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
