"""Konversi katalog: `ptn.csv` dan `prodi.csv` (prodi + data keketatan per jalur)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.domain.provinsi import normalisasi_provinsi
from app.ingest.umum import (
    ErrorBaris,
    Kebijakan,
    ambil_daftar,
    ambil_int,
    ambil_tanggal,
    ambil_url,
    proses_baris,
    teks,
)

JALUR = ("SNBP", "SNBT")
JENJANG_PETA = {
    "sarjana": "S1",
    "s1": "S1",
    "diploma tiga": "D3",
    "d3": "D3",
    "sarjana terapan": "D4",
    "diploma empat": "D4",
    "d4": "D4",
}
PROGRAM_PER_JENJANG = {"S1": "akademik", "D3": "vokasi", "D4": "vokasi"}


def _ptn(b: Mapping[str, Any], k: Kebijakan) -> dict[str, Any]:
    ptn_id = teks(b, "ptn_id")
    if not ptn_id:
        raise ValueError("ptn_id wajib diisi")
    nama = teks(b, "nama")
    if not nama:
        raise ValueError("nama wajib diisi")
    mentah = teks(b, "provinsi")
    provinsi = normalisasi_provinsi(mentah)
    if provinsi is None:
        raise ValueError(
            f"provinsi '{mentah}' bukan provinsi baku. Tetapkan satu nilai pasti dari daftar 38 provinsi"
        )
    return {
        "id": ptn_id,
        "nama": nama,
        "provinsi": provinsi,
        "sumber_url": ambil_url(b, wajib=False),
        "terakhir_diverifikasi": ambil_tanggal(b, k),
    }


def _prodi(b: Mapping[str, Any], k: Kebijakan, tahun_default: int | None) -> dict[str, Any]:
    prodi_id, ptn_id = teks(b, "prodi_id"), teks(b, "ptn_id")
    if not prodi_id:
        raise ValueError("prodi_id wajib diisi")
    if not ptn_id:
        raise ValueError("ptn_id wajib diisi")
    nama, rumpun = teks(b, "nama"), teks(b, "rumpun")
    if not nama or not rumpun:
        raise ValueError("nama dan rumpun wajib diisi")

    mentah_jenjang = teks(b, "jenjang")
    jenjang = JENJANG_PETA.get(mentah_jenjang.casefold())
    if jenjang is None:
        raise ValueError(
            f"jenjang '{mentah_jenjang}' tidak dikenal (Sarjana, Diploma Tiga, Sarjana Terapan)"
        )
    program = teks(b, "program").casefold()
    if program not in ("akademik", "vokasi"):
        raise ValueError(f"program harus 'akademik' atau 'vokasi', bukan '{program}'")
    if PROGRAM_PER_JENJANG[jenjang] != program:
        raise ValueError(f"jenjang {jenjang} tidak sesuai program '{program}'")

    jalur_dibuka = ambil_daftar(b, "jalur_dibuka")
    if jalur_dibuka is not None:
        jalur_dibuka = [j.upper() for j in jalur_dibuka]
        salah = [j for j in jalur_dibuka if j not in JALUR]
        if salah:
            raise ValueError(f"jalur_dibuka berisi jalur tidak dikenal: {salah}")

    # Data keketatan per jalur: kolom per-jalur, atau kolom lama bila jalur_dibuka tepat satu.
    per_jalur: dict[str, tuple[int | None, int | None]] = {}
    for jalur in JALUR:
        dt = ambil_int(b, f"daya_tampung_{jalur.lower()}", minimum=1)
        pm = ambil_int(b, f"peminat_{jalur.lower()}", minimum=0)
        if dt is not None or pm is not None:
            per_jalur[jalur] = (dt, pm)
    dt_lama = ambil_int(b, "daya_tampung", minimum=1)
    pm_lama = ambil_int(b, "peminat_tahun_lalu", minimum=0)
    if (dt_lama is not None or pm_lama is not None) and not per_jalur:
        if not jalur_dibuka or len(jalur_dibuka) != 1:
            raise ValueError(
                "daya_tampung/peminat_tahun_lalu hanya boleh diisi bila jalur_dibuka tepat satu jalur; "
                "untuk dua jalur pakai daya_tampung_snbp, peminat_snbp, daya_tampung_snbt, peminat_snbt"
            )
        per_jalur[jalur_dibuka[0]] = (dt_lama, pm_lama)
    for jalur in per_jalur:
        if jalur_dibuka is None or jalur not in jalur_dibuka:
            raise ValueError(f"ada data keketatan {jalur} tetapi {jalur} tidak ada di jalur_dibuka")

    ada_data = bool(per_jalur) or jalur_dibuka is not None
    sumber = ambil_url(b, wajib=ada_data)
    tanggal = ambil_tanggal(b, k) if ada_data else None

    tahun_mentah = teks(b, "tahun_siklus")
    tahun = int(tahun_mentah) if tahun_mentah.isdigit() else tahun_default
    if per_jalur and tahun is None:
        raise ValueError(
            "tahun_siklus tidak diketahui (isi kolom tahun_siklus atau ketentuan tahun_acuan_pendaftaran)"
        )

    return {
        "prodi": {
            "id": prodi_id,
            "ptn_id": ptn_id,
            "nama": nama,
            "rumpun": rumpun,
            "akreditasi": teks(b, "akreditasi") or None,
            "jenjang": jenjang,
            "program": program,
            "mapel_penentu": ambil_daftar(b, "mapel_penentu"),
            "tag_minat": ambil_daftar(b, "tag_minat"),
            "jalur_dibuka": jalur_dibuka,
            "sumber_url": sumber,
            "terakhir_diverifikasi": tanggal,
        },
        "prodi_jalur": [
            {
                "prodi_id": prodi_id,
                "jalur": jalur,
                "tahun_siklus": tahun,
                "daya_tampung": dt,
                "peminat": pm,
                "tahun_peminat": tahun - 1 if pm is not None else None,  # 'peminat tahun lalu'
                "sumber_url": sumber,
                "terakhir_diverifikasi": tanggal,
            }
            for jalur, (dt, pm) in per_jalur.items()
        ],
    }


@dataclass
class HasilKatalog:
    ptn: list[dict[str, Any]]
    prodi: list[dict[str, Any]]
    prodi_jalur: list[dict[str, Any]]
    baris_prodi: dict[str, int]  # prodi_id -> nomor baris (untuk error referensi)
    error: list[ErrorBaris]
    ptn_ditolak: set[str] = field(
        default_factory=set
    )  # PTN yang barisnya salah (redam error berantai)


def katalog_dari_baris(
    baris: Iterable[Mapping[str, Any]], kebijakan: Kebijakan, *, tahun_default: int | None = None
) -> HasilKatalog:
    """Baris campuran: baris ber-`prodi_id` = prodi, selain itu = PTN."""
    baris = list(baris)

    def konversi(b: Mapping[str, Any]) -> tuple[str, Any]:
        if teks(b, "prodi_id"):
            return "prodi", _prodi(b, kebijakan, tahun_default)
        return "ptn", _ptn(b, kebijakan)

    hasil, galat = proses_baris(baris, "katalog", konversi)
    ptn: dict[str, dict[str, Any]] = {}
    prodi: dict[str, dict[str, Any]] = {}
    nomor: dict[str, int] = {}
    jalur: list[dict[str, Any]] = []
    for no, (jenis, item) in hasil:
        if jenis == "ptn":
            if item["id"] in ptn:
                galat.append(
                    ErrorBaris("katalog", no, f"ptn_id '{item['id']}' duplikat dalam satu batch")
                )
                continue
            ptn[item["id"]] = item
        else:
            pid = item["prodi"]["id"]
            if pid in prodi:
                galat.append(
                    ErrorBaris("katalog", no, f"prodi_id '{pid}' duplikat dalam satu batch")
                )
                continue
            prodi[pid] = item["prodi"]
            nomor[pid] = no
            jalur.extend(item["prodi_jalur"])
    ditolak = {
        teks(baris[e.baris - 1], "ptn_id")
        for e in galat
        if e.baris <= len(baris) and not teks(baris[e.baris - 1], "prodi_id")
    }
    return HasilKatalog(
        list(ptn.values()),
        list(prodi.values()),
        jalur,
        nomor,
        sorted(galat, key=lambda e: e.baris),
        ditolak,
    )
