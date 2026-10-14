"""Penyusun ringkasan strategi (FR-R1): murni dan deterministik. Tanpa LLM.

Semua angka dan status berasal dari hasil mesin aturan (dict hasil `analisis_satu`). Fungsi di sini
hanya menurunkan "fokus persiapan" dari gap/faktor terlemah dan menyusun teks template.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any

SEMESTER_DIPAKAI = ("semester_1", "semester_2", "semester_3", "semester_4", "semester_5")
URUTAN_FAKTOR = ("rapor", "peringkat", "tren")  # urutan tie-break bila nilai faktor sama
PESAN_FAKTOR = {
    "rapor": "Tingkatkan nilai rapor (rata-rata semester 1 sampai 5 saat ini {nilai:.0f} dari 100).",
    "tren": "Jaga kenaikan nilai rapor di semester-semester berikutnya (tren nilai adalah faktor terlemahmu).",
    "peringkat": "Naikkan peringkat di angkatan sekolahmu (peringkat adalah faktor terlemahmu).",
}


def rata_mapel(profil: Mapping[str, Any], mapel: Sequence[str]) -> dict[str, float]:
    """Rata-rata nilai rapor semester 1-5 per mapel (hanya mapel yang punya data)."""
    rapor = profil.get("nilai_rapor") or {}
    hasil: dict[str, float] = {}
    for m in mapel:
        nilai = [
            float(rapor[s][m])
            for s in SEMESTER_DIPAKAI
            if isinstance(rapor.get(s), Mapping) and rapor[s].get(m) is not None
        ]
        if nilai:
            hasil[m] = fmean(nilai)
    return hasil


def _faktor_terlemah(penilaian: Mapping[str, Any]) -> tuple[str, float] | None:
    tier = penilaian.get("tier") or {}
    faktor = tier.get("faktor") or {}
    if not faktor:
        return None
    nama = min(
        faktor, key=lambda f: (faktor[f], URUTAN_FAKTOR.index(f) if f in URUTAN_FAKTOR else 99)
    )
    return nama, faktor[nama]


def fokus_satu_pilihan(
    jalur: str,
    hasil: Mapping[str, Any],
    profil: Mapping[str, Any],
    mapel_penentu: Sequence[str] | None,
) -> list[dict[str, Any]]:
    """Fokus persiapan satu pilihan, diturunkan deterministik dari gap/faktor terlemah."""
    pid, nama = hasil["prodi_id"], hasil["prodi"]["nama"]
    item = lambda jenis, pesan: {"jalur": jalur, "jenis": jenis, "pesan": pesan, "prodi_ids": [pid]}  # noqa: E731
    gate = hasil["gate"]
    penilaian = hasil.get("penilaian")

    if gate["status"] == "tidak_memenuhi_syarat":
        gagal = [s["alasan"] for s in gate["syarat"] if s["status"] == "gagal" and s.get("alasan")]
        return [item("syarat", f"{nama} tidak memenuhi syarat {jalur}: " + "; ".join(gagal) + ".")]
    if gate["status"] == "data_kurang" or hasil.get("data_kurang"):
        lengkapi = ", ".join(d["field"] for d in hasil["data_kurang"]) or "profil"
        return [item("data", f"Lengkapi data agar {nama} bisa dinilai: {lengkapi}.")]

    hasil_fokus: list[dict[str, Any]] = []
    if penilaian is not None:
        if penilaian.get("gap"):
            acuan = penilaian.get("acuan") or {}
            hasil_fokus.append(
                item(
                    "skor_tryout",
                    f"Naikkan skor tryout sekitar {penilaian['gap']:g} poin untuk mencapai batas bawah "
                    f"acuan {acuan.get('rendah', 0):g} ({nama}).",
                )
            )
        elif penilaian["kategori"] in ("reach", "match"):
            terlemah = _faktor_terlemah(penilaian)
            if terlemah:
                f, nilai = terlemah
                hasil_fokus.append(item(f"faktor_{f}", PESAN_FAKTOR[f].format(nilai=nilai * 100)))
        elif penilaian["kategori"] == "safe":
            hasil_fokus.append(
                item("pertahankan", f"Pertahankan nilai dan peringkatmu untuk {nama}.")
            )

    if mapel_penentu:
        rata = rata_mapel(profil, mapel_penentu)
        if rata:
            terendah = min(rata, key=lambda m: (rata[m], m))
            hasil_fokus.append(
                item(
                    "mapel_penentu",
                    f"Mapel penentu {nama}: {terendah.replace('_', ' ')} adalah yang terendah "
                    f"(rata-rata {rata[terendah]:.0f}).",
                )
            )
    return hasil_fokus


def gabung_fokus(daftar: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gabungkan fokus yang sama (jalur, jenis, pesan) dari beberapa prodi; urutan kemunculan dijaga."""
    unik: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in daftar:
        kunci = (f["jalur"], f["jenis"], f["pesan"])
        if kunci in unik:
            unik[kunci]["prodi_ids"] = [
                *unik[kunci]["prodi_ids"],
                *(p for p in f["prodi_ids"] if p not in unik[kunci]["prodi_ids"]),
            ]
        else:
            unik[kunci] = {**f, "prodi_ids": list(f["prodi_ids"])}
    return list(unik.values())


KALIMAT_PENUTUP = (
    "Kategori reach, match, dan safe adalah heuristik indikatif dari data acuan, bukan peluang atau jaminan "
    "diterima. Keputusan syarat dan kategori berasal dari mesin aturan, bukan dari AI."
)


def narasi_template(bagian: Sequence[Mapping[str, Any]]) -> str:
    """Narasi ringkas dari template. `bagian` = [{jalur, pilihan:[{nama,ptn,kategori,status}], pelanggaran:int}]."""
    kalimat: list[str] = []
    for b in bagian:
        pil = "; ".join(f"{p['nama']} ({p['ptn']}), {_istilah_status(p)}" for p in b["pilihan"])
        kalimat.append(f"Pilihan {b['jalur']}: {pil}.")
        if b["pelanggaran"]:
            kalimat.append(
                f"Ada {b['pelanggaran']} aturan {b['jalur']} yang perlu diperbaiki sebelum mendaftar."
            )
    kalimat.append(KALIMAT_PENUTUP)
    return " ".join(kalimat)


def fakta_narasi(bagian: Sequence[Mapping[str, Any]], tahun_siklus: int) -> dict[str, Any]:
    """Fakta untuk narasi LLM. Hanya hasil mesin aturan; tanpa data profil siswa (bebas PII).

    `bagian` = bagian narasi per jalur: {jalur, batas_pilihan, komposisi, pelanggaran, peringatan,
    pilihan:[{nama, ptn, kategori, status, keyakinan}]}. Tidak ada angka lain yang boleh dipakai LLM:
    pagar keluaran menolak angka di luar dict ini.
    """
    return {
        "tahun_siklus": tahun_siklus,
        "memuat_snbp_dan_snbt": len(bagian) > 1,
        "jalur": [
            {
                "jalur": b["jalur"],
                "jumlah_pilihan": b["komposisi"]["jumlah"],
                "batas_pilihan": b["batas_pilihan"],
                "komposisi": {
                    k: b["komposisi"][k] for k in ("reach", "match", "safe", "tidak_dinilai")
                },
                "aturan_dilanggar": b["pelanggaran"],
                "peringatan": b["peringatan"],
                "pilihan": [
                    {
                        "prodi": p["nama"],
                        "ptn": p["ptn"],
                        "kategori": p["kategori"] or "belum_dinilai",
                        "status_syarat": p["status"],
                        "keyakinan": p["keyakinan"],
                    }
                    for p in b["pilihan"]
                ],
            }
            for b in bagian
        ],
    }


def _istilah_status(p: Mapping[str, Any]) -> str:
    if p["status"] == "tidak_memenuhi_syarat":
        return "tidak memenuhi syarat"
    if p["status"] == "data_kurang" or p["kategori"] == "data_kurang":
        return "data belum lengkap"
    if p["kategori"] == "belum_ada_acuan":
        return "belum ada data acuan"
    return f"kategori {p['kategori']}"


def catatan_ringkasan(hasil_semua: Sequence[Mapping[str, Any]], jumlah_jalur: int) -> list[str]:
    catatan = [
        "Kategori reach, match, dan safe bersifat indikatif (heuristik), bukan peluang atau jaminan.",
    ]
    penilaian = [h["penilaian"] for h in hasil_semua if h.get("penilaian")]
    if any(
        p.get("label") == "acuan siklus sebelumnya"
        or any("siklus sebelumnya" in c for c in p.get("catatan", []))
        for p in penilaian
    ):
        catatan.append(
            "Sebagian data acuan berasal dari siklus sebelumnya. Cek ulang saat pendaftaran dibuka."
        )
    if any("belum dikalibrasi" in (p.get("label") or "") for p in penilaian):
        catatan.append(
            "Bobot, batas, dan matriks penilaian masih nilai awal dan belum dikalibrasi tim data, "
            "jadi kategori hanya indikatif."
        )
    if any(h["status_verifikasi"] == "belum_diverifikasi" for h in hasil_semua):
        catatan.append(
            "Sebagian data belum diverifikasi tim data (lihat status_verifikasi). Cek ke sumber resmi sebelum memutuskan."
        )
    if any(
        p["metode"] == "matriks_keketatan"
        and p.get("tier", {})
        and p["tier"]["sumber"] == "proksi_rapor"
        for p in penilaian
    ):
        catatan.append(
            "Penilaian SNBT memakai proksi dari rapor, bukan skor UTBK, sehingga keyakinannya rendah."
        )
    if jumlah_jalur > 1:
        catatan.append(
            "Lulus SNBP menutup kesempatan ikut UTBK-SNBT dan seleksi Mandiri. Pertimbangkan ini saat memilih."
        )
    return catatan
