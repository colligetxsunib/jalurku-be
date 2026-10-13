"""Render halaman HTML statis ringkasan persona fiktif (PRD bagian 9: tautan untuk juri).

Fungsi murni (tanpa I/O, DB, atau sesi). Halaman dibuat offline oleh scripts/export_persona_static.py
dari data persona, disajikan sebagai berkas statis oleh reverse proxy, dan tidak punya akses ke data
pengguna. Semua teks di-escape; tautan hanya http(s); tanpa JavaScript dan tanpa sumber eksternal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

from app.services.persona import Persona

BANNER = "Contoh dengan persona fiktif. Ini bukan data siswa nyata dan bukan hasil untuk siapa pun."
PENUTUP = (
    "Kategori reach, match, dan safe adalah heuristik indikatif dari data acuan, bukan peluang atau "
    "jaminan diterima. Keputusan syarat dan kategori berasal dari mesin aturan, bukan dari AI. "
    "Cek ke sumber resmi (snpmb.id) sebelum mendaftar."
)
LABEL_GATE = {
    "lolos": "Memenuhi syarat",
    "tidak_memenuhi_syarat": "Belum memenuhi syarat",
    "data_kurang": "Data belum lengkap",
}
LABEL_KATEGORI = {
    "reach": "Reach",
    "match": "Match",
    "safe": "Safe",
    "belum_ada_acuan": "Belum ada data acuan",
    "data_kurang": "Data belum lengkap",
}
LABEL_KEYAKINAN = {"rendah": "rendah", "sedang": "sedang", "tinggi": "tinggi"}
LABEL_TINGKAT = {"pelanggaran": "Perlu diperbaiki", "peringatan": "Perhatian", "info": "Info"}
LABEL_VERIFIKASI = {
    "terverifikasi": "terverifikasi tim data",
    "belum_diverifikasi": "belum diverifikasi tim data",
}

CSS = """
:root{color-scheme:light}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.55;color:#1b1f23;
background:#f6f7f9;margin:0}
main{max-width:56rem;margin:0 auto;padding:1rem}
.banner{background:#fff3cd;border:2px solid #7a5c00;color:#4a3700;padding:.75rem 1rem;border-radius:.5rem;
font-weight:600}
h1{font-size:1.5rem;margin:1rem 0 .25rem}h2{font-size:1.2rem;margin:1.5rem 0 .5rem}
section{background:#fff;border:1px solid #d0d7de;border-radius:.5rem;padding:.75rem 1rem;margin:1rem 0}
.tabel{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{border:1px solid #d0d7de;padding:.4rem .5rem;text-align:left;vertical-align:top}
th{background:#eef1f4}caption{text-align:left;font-weight:600;padding:.25rem 0}
.kecil{font-size:.9rem;color:#454d55}a{color:#0b4fa8}
footer{font-size:.9rem;color:#454d55;margin:1.5rem 0 2rem}
"""


def _e(nilai: Any) -> str:
    return escape("" if nilai is None else str(nilai), quote=True)


def _tautan(url: str | None, teks: str) -> str:
    """Tautan hanya untuk http(s); selain itu teks biasa (mencegah javascript: dan sejenisnya)."""
    if url and url.lower().startswith(("http://", "https://")):
        return f'<a href="{_e(url)}" rel="noopener noreferrer">{_e(teks)}</a>'
    return _e(teks)


def _dokumen(judul: str, isi: str) -> str:
    return (
        '<!doctype html>\n<html lang="id">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex">\n'
        f"<title>{_e(judul)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f'<p class="banner" role="note">{_e(BANNER)}</p>\n{isi}\n</main>\n</body>\n</html>\n'
    )


def _tabel_pilihan(jalur: str, pilihan: Sequence[Mapping[str, Any]]) -> str:
    baris = []
    for p in pilihan:
        kategori = LABEL_KATEGORI.get(p["kategori"] or "", "Belum dinilai")
        yakin = LABEL_KEYAKINAN.get(p["keyakinan"] or "", "-")
        baris.append(
            "<tr>"
            f"<td>{_e(p['urutan'])}</td>"
            f'<td>{_e(p["prodi"])}<br><span class="kecil">{_e(p["ptn"])} ({_e(p["jenjang"])})</span></td>'
            f"<td>{_e(LABEL_GATE.get(p['status_gate'], p['status_gate']))}</td>"
            f"<td>{_e(kategori)}</td><td>{_e(yakin)}</td><td>{_e(p['alasan'])}"
            f'<br><span class="kecil">Data {_e(LABEL_VERIFIKASI.get(p["status_verifikasi"], p["status_verifikasi"]))}'
            "</span></td></tr>"
        )
    return (
        f'<div class="tabel"><table><caption>Pilihan {_e(jalur)}</caption><thead><tr>'
        '<th scope="col">No</th><th scope="col">Program studi</th><th scope="col">Syarat</th>'
        '<th scope="col">Kategori (indikatif)</th><th scope="col">Keyakinan</th>'
        '<th scope="col">Alasan</th></tr></thead><tbody>'
        + "".join(baris)
        + "</tbody></table></div>"
    )


def _daftar(item: Sequence[str]) -> str:
    return "<ul>" + "".join(f"<li>{x}</li>" for x in item) + "</ul>" if item else ""


def render_ringkasan(persona: Persona, ringkasan: Mapping[str, Any], dibuat: str) -> str:
    """Satu halaman HTML dari respons POST /summary untuk persona fiktif."""
    bagian: list[str] = [f"<h1>Ringkasan strategi: {_e(persona.nama)}</h1>"]
    bagian.append(f"<p>{_e(persona.deskripsi)}</p>")

    jalur_urut = list(dict.fromkeys(p["jalur"] for p in ringkasan["pilihan_akhir"]))
    bagian.append("<section><h2>Pilihan akhir</h2>")
    for jalur in jalur_urut:
        bagian.append(
            _tabel_pilihan(jalur, [p for p in ringkasan["pilihan_akhir"] if p["jalur"] == jalur])
        )
    bagian.append("</section>")

    bagian.append(f"<section><h2>Ringkasan</h2><p>{_e(ringkasan['narasi'])}</p>")
    bagian.append(_daftar([_e(a) for a in ringkasan["alasan"]]) + "</section>")

    temuan = [(s["jalur"], t) for s in ringkasan["strategi"] for t in s["temuan"]]
    if temuan:
        bagian.append("<section><h2>Temuan pada strategi</h2>")
        bagian.append(
            _daftar(
                [
                    f"<strong>{_e(j)}, {_e(LABEL_TINGKAT.get(t['tingkat'], t['tingkat']))}:</strong> {_e(t['pesan'])}"
                    for j, t in temuan
                ]
            )
            + "</section>"
        )

    if ringkasan["fokus_persiapan"]:
        bagian.append("<section><h2>Fokus persiapan</h2>")
        bagian.append(
            _daftar([f"{_e(f['jalur'])}: {_e(f['pesan'])}" for f in ringkasan["fokus_persiapan"]])
            + "</section>"
        )

    if ringkasan["dokumen_syarat"]:
        bagian.append("<section><h2>Dokumen yang perlu disiapkan</h2>")
        bagian.append(
            _daftar(
                [
                    f"{_e(d['jalur'])}: {_tautan(d['sumber_url'], d['nama'])} "
                    f'<span class="kecil">({_e(LABEL_VERIFIKASI.get(d["status_verifikasi"], d["status_verifikasi"]))})</span>'
                    for d in ringkasan["dokumen_syarat"]
                ]
            )
            + "</section>"
        )

    bagian.append("<section><h2>Catatan</h2>" + _daftar([_e(c) for c in ringkasan["catatan"]]))
    bagian.append("</section>")
    bagian.append(f"<footer><p>{_e(PENUTUP)}</p><p>Dibuat {_e(dibuat)}.</p></footer>")
    return _dokumen(f"Contoh ringkasan strategi: {persona.nama}", "\n".join(bagian))


def render_indeks(daftar: Sequence[tuple[Persona, str]], dibuat: str) -> str:
    """Halaman indeks: [(persona, nama_berkas)]."""
    item = [
        f'<a href="{_e(berkas)}">{_e(p.nama)}</a><br><span class="kecil">{_e(p.deskripsi)}</span>'
        for p, berkas in daftar  # berkas = nama berkas lokal dari id persona (divalidasi regex)
    ]
    isi = (
        "<h1>Contoh ringkasan strategi JalurKu</h1>"
        "<p>Halaman statis dari persona fiktif untuk keperluan penilaian. "
        "Tidak ada data pengguna di halaman ini.</p>"
        f"<section><h2>Persona</h2>{_daftar(item)}</section>"
        f"<footer><p>{_e(PENUTUP)}</p><p>Dibuat {_e(dibuat)}.</p></footer>"
    )
    return _dokumen("Contoh ringkasan strategi JalurKu", isi)
