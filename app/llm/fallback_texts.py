"""Teks cadangan bila LLM/embedding gagal, plus penjelasan deterministik dari hasil mesin aturan.

Bebas diubah tanpa revisi PRD (hanya teks).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SUMBER_RESMI_PESAN = "Cek langsung di sumber resmi (snpmb.id) atau tanyakan ke guru BK sekolahmu."
TEKS_TIDAK_YAKIN = (
    "Aku belum menemukan jawaban yang pasti di dokumen resmi yang kupunya. " + SUMBER_RESMI_PESAN
)
TEKS_LAYANAN_GAGAL = (
    "Layanan penjelasan otomatis sedang tidak tersedia, jadi aku belum bisa menjawab pertanyaan ini. "
    + SUMBER_RESMI_PESAN
)
TEKS_JELASKAN_PENGANTAR = (
    "Penjelasan otomatis sedang tidak tersedia. Berikut hasil dari mesin aturan: "
)
TEKS_ALIH_EKSPLORASI = (
    "Pertanyaan tentang minat dan pilihan jurusan paling pas dijawab lewat fitur Eksplorasi Jurusan, "
    "bukan dari dokumen resmi seleksi. Isi minat dan nilai rapormu di sana (kamu juga bisa ikut tes "
    "minat), lalu kamu akan melihat rumpun jurusan yang cocok beserta PTN yang membukanya. "
    "Hasilnya gambaran awal untuk membantumu menjajaki pilihan."
)


def catatan_dokumen_terkait(tahun_siklus: int) -> str:
    """Peringatan wajib bila `yakin` false tetapi dokumen terkait ditampilkan."""
    return (
        f"Dokumen terkait di bawah hanya bahan bacaan (siklus {tahun_siklus}), bukan jawaban atas "
        "pertanyaanmu. Ketentuan dan jadwal siklus lain bisa berbeda."
    )


TEKS_KEPUTUSAN_TANPA_KONTEKS = (
    "Keputusan syarat dan kategori ditentukan mesin aturan di aplikasi, bukan oleh AI. "
    "Pilih prodi dan jalur yang ingin dicek lewat fitur analisis agar aku bisa merujuk hasilnya."
)


def penjelasan_dari_hasil(hasil: Mapping[str, Any]) -> str:
    """Penjelasan deterministik dari satu hasil `analisis_satu` (dipakai sebagai teks fallback)."""
    nama = hasil["prodi"]["nama"]
    ptn = hasil["prodi"]["ptn_nama"]
    jalur = hasil["jalur"]
    gate = hasil["gate"]
    kepala = f"{nama} ({ptn}), jalur {jalur}: "

    if gate["status"] == "tidak_memenuhi_syarat":
        gagal = [s["alasan"] for s in gate["syarat"] if s["status"] == "gagal" and s.get("alasan")]
        return kepala + "belum memenuhi syarat. " + " ".join(f"{a}." for a in gagal)
    if gate["status"] == "data_kurang" or hasil.get("data_kurang"):
        ditanya = " ".join(d["pertanyaan"] for d in hasil["data_kurang"])
        return kepala + "datamu belum lengkap, jadi belum bisa dinilai. " + ditanya

    p = hasil.get("penilaian")
    if p is None:
        return kepala + "syarat terpenuhi."
    teks = kepala + "syarat terpenuhi. " + p["alasan"]
    if p.get("catatan"):
        teks += " " + " ".join(p["catatan"])
    return teks
