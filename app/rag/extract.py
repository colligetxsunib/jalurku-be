"""Ekstraksi teks dari berkas dokumen sumber (PDF, HTML tersimpan, teks biasa)."""

from __future__ import annotations

import logging
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

log = logging.getLogger("jalurku.rag.extract")
EKSTENSI = (".pdf", ".html", ".htm", ".txt", ".md")


class BerkasTidakAda(FileNotFoundError):
    pass


class TanpaTeks(ValueError):
    """Berkas tidak memuat teks yang bisa diekstrak (mis. PDF hasil scan)."""


def cari_berkas(direktori: str | Path, dokumen_id: str) -> Path:
    d = Path(direktori)
    for ext in EKSTENSI:
        p = d / f"{dokumen_id}{ext}"
        if p.is_file():
            return p
    raise BerkasTidakAda(
        f"Berkas untuk dokumen '{dokumen_id}' tidak ditemukan di {d}. "
        f"Unduh manual dan simpan sebagai {dokumen_id}.pdf (atau .html/.txt)."
    )


def _pdf(path: Path) -> list[tuple[int | None, str]]:
    pembaca = PdfReader(str(path), strict=False)
    return [(i, (hal.extract_text() or "")) for i, hal in enumerate(pembaca.pages, start=1)]


def _html(path: Path) -> list[tuple[int | None, str]]:
    sup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in sup(["script", "style", "noscript", "nav", "footer", "header", "form", "svg"]):
        tag.decompose()
    return [(None, sup.get_text(separator="\n"))]


def ekstrak(path: str | Path) -> list[tuple[int | None, str]]:
    """Kembalikan [(halaman | None, teks)]. Melempar TanpaTeks bila seluruhnya kosong."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        hasil = _pdf(p)
    elif ext in (".html", ".htm"):
        hasil = _html(p)
    elif ext in (".txt", ".md"):
        hasil = [(None, p.read_text(encoding="utf-8", errors="replace"))]
    else:
        raise ValueError(f"jenis berkas tidak didukung: {ext}")
    if not any(t.strip() for _, t in hasil):
        raise TanpaTeks(f"{p.name} tidak memuat teks yang bisa diekstrak (mungkin PDF hasil scan)")
    return hasil
