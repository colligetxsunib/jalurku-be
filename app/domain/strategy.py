"""Evaluasi komposisi pilihan prodi (PRD 8.4). Fungsi murni, tidak meng-import klien LLM.

Dua lapis aturan:
- ATURAN KERAS (tingkat `pelanggaran`) dari ketentuan resmi: batas jumlah pilihan per jalur, aturan
  provinsi SNBP, komposisi akademik/vokasi/D3 SNBT. Dibaca dari data, bukan di-hardcode angkanya.
- HEURISTIK (tingkat `peringatan`/`info`) dari config: minimal safe, maksimal porsi reach, dst.

Evaluasi PER JALUR. Pilihan yang tidak dapat dinilai (gate tidak lolos, data_kurang, belum_ada_acuan)
tidak dihitung dalam rasio, tetapi dilaporkan sebagai temuan tersendiri.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

KATEGORI_NILAI = ("reach", "match", "safe")
TINGKAT_URUT = {"pelanggaran": 0, "peringatan": 1, "info": 2}
KODE_URUT = (
    "melebihi_batas_pilihan",
    "provinsi_sekolah_asal",
    "butuh_vokasi",
    "komposisi_snbt_tidak_valid",
    "provinsi_sekolah_belum_diisi",
    "pilihan_tidak_memenuhi_syarat",
    "min_safe",
    "maks_reach",
    "satu_ptn",
    "pilihan_data_kurang",
    "pilihan_belum_ada_acuan",
    "evaluasi_rasio_dilewati",
    "blokir_lintas_jalur",
    "hanya_satu_jalur",
)
# Temuan yang menunjuk prodi tertentu: dihitung per prodi saat membandingkan sebelum/sesudah swap.
KODE_PER_PRODI = frozenset(
    {"pilihan_tidak_memenuhi_syarat", "pilihan_data_kurang", "pilihan_belum_ada_acuan"}
)
LABEL_PERBAIKAN = {
    "melebihi_batas_pilihan": "jumlah pilihan melebihi batas",
    "provinsi_sekolah_asal": "belum ada pilihan di provinsi sekolah asal",
    "butuh_vokasi": "komposisi belum memuat program vokasi",
    "komposisi_snbt_tidak_valid": "komposisi akademik/vokasi belum sesuai ketentuan",
    "pilihan_tidak_memenuhi_syarat": "ada pilihan yang tidak memenuhi syarat jalur",
    "min_safe": "belum ada pilihan safe",
    "maks_reach": "terlalu banyak pilihan reach",
    "satu_ptn": "semua pilihan berada di satu PTN",
}


@dataclass(frozen=True)
class Pilihan:
    prodi_id: str
    nama: str
    ptn_id: str
    ptn_nama: str
    provinsi_ptn: str
    program: str  # akademik | vokasi
    jenjang: str  # S1 | D3 | D4
    status_gate: str  # lolos | tidak_memenuhi_syarat | data_kurang
    kategori: str | None  # reach | match | safe | belum_ada_acuan | data_kurang | None

    @property
    def dapat_dinilai(self) -> bool:
        return self.status_gate == "lolos" and self.kategori in KATEGORI_NILAI


@dataclass(frozen=True)
class AturanStrategi:
    jalur: str
    max_pilihan: int
    komposisi: Mapping[int, Any] | None  # n -> "bebas" | [{akademik, vokasi, min_d3}]
    aturan_provinsi: bool
    blokir_lintas_jalur: bool
    min_pilihan_untuk_evaluasi: int
    min_safe: int
    maks_rasio_reach: float
    peringatan_satu_ptn: bool
    peringatan_satu_jalur: bool
    maks_saran_swap: int


@dataclass(frozen=True)
class Saran:
    ganti: str
    dengan: str
    alasan: str

    def ke_dict(self) -> dict[str, str]:
        return {"ganti": self.ganti, "dengan": self.dengan, "alasan": self.alasan}


@dataclass(frozen=True)
class Temuan:
    kode: str
    tingkat: str  # info | peringatan | pelanggaran
    pesan: str
    prodi_ids: tuple[str, ...] = ()
    data_kurang: tuple[str, ...] = ()
    saran_swap: tuple[Saran, ...] = field(default=())

    def ke_dict(self) -> dict[str, Any]:
        return {
            "kode": self.kode,
            "tingkat": self.tingkat,
            "pesan": self.pesan,
            "prodi_ids": list(self.prodi_ids),
            "data_kurang": list(self.data_kurang),
            "saran_swap": [s.ke_dict() for s in self.saran_swap],
        }


# ----------------------------------------------------------------------------- komposisi


def hitung_komposisi(pilihan: Sequence[Pilihan]) -> dict[str, int]:
    dinilai = [p for p in pilihan if p.dapat_dinilai]
    return {
        "jumlah": len(pilihan),
        "reach": sum(p.kategori == "reach" for p in dinilai),
        "match": sum(p.kategori == "match" for p in dinilai),
        "safe": sum(p.kategori == "safe" for p in dinilai),
        "tidak_dinilai": len(pilihan) - len(dinilai),
        "akademik": sum(p.program == "akademik" for p in pilihan),
        "vokasi": sum(p.program == "vokasi" for p in pilihan),
        "d3": sum(p.jenjang == "D3" for p in pilihan),
    }


def _uraikan_komposisi(daftar: Sequence[Mapping[str, int]]) -> str:
    bagian = []
    for c in daftar:
        teks = f"{c['akademik']} akademik + {c['vokasi']} vokasi"
        if c["min_d3"]:
            teks += f" (minimal {c['min_d3']} D3)"
        bagian.append(teks)
    return "; ".join(bagian)


def _nama(pilihan: Sequence[Pilihan], ids: Sequence[str]) -> str:
    peta = {p.prodi_id: p for p in pilihan}
    return ", ".join(f"{peta[i].nama} ({peta[i].ptn_nama})" for i in ids if i in peta)


def evaluasi(
    pilihan: Sequence[Pilihan],
    aturan: AturanStrategi,
    *,
    provinsi_sekolah: str | None,
    ada_strategi_jalur_lain: bool,
) -> list[Temuan]:
    n = len(pilihan)
    k = hitung_komposisi(pilihan)
    temuan: list[Temuan] = []
    if n == 0:
        return temuan

    # --- aturan keras ---
    melebihi = n > aturan.max_pilihan
    if melebihi:
        temuan.append(
            Temuan(
                "melebihi_batas_pilihan",
                "pelanggaran",
                f"{aturan.jalur} maksimal {aturan.max_pilihan} pilihan program studi; "
                f"kamu memilih {n}. Kurangi {n - aturan.max_pilihan} pilihan.",
            )
        )

    if aturan.aturan_provinsi and 2 <= n <= aturan.max_pilihan:
        if provinsi_sekolah is None:
            temuan.append(
                Temuan(
                    "provinsi_sekolah_belum_diisi",
                    "peringatan",
                    "Provinsi sekolah asal belum diisi, sehingga aturan provinsi pilihan SNBP "
                    "(salah satu dari 2 pilihan harus di PTN provinsi sekolah asal) belum bisa diperiksa.",
                    data_kurang=("provinsi",),
                )
            )
        elif not any(p.provinsi_ptn == provinsi_sekolah for p in pilihan):
            temuan.append(
                Temuan(
                    "provinsi_sekolah_asal",
                    "pelanggaran",
                    f"Bila memilih 2 prodi di SNBP, salah satunya harus di PTN provinsi sekolah asal "
                    f"({provinsi_sekolah}). Tidak ada pilihanmu yang memenuhi.",
                )
            )

    if aturan.komposisi and not melebihi and n in aturan.komposisi:
        sah = aturan.komposisi[n]
        if sah != "bebas" and not any(
            c["akademik"] == k["akademik"] and c["vokasi"] == k["vokasi"] and k["d3"] >= c["min_d3"]
            for c in sah
        ):
            uraian = _uraikan_komposisi(sah)
            if k["vokasi"] == 0:
                temuan.append(
                    Temuan(
                        "butuh_vokasi",
                        "pelanggaran",
                        f"{n} pilihan SNBT wajib memuat program vokasi, sehingga Sarjana maksimal 2. "
                        f"Kamu memilih {k['akademik']} akademik dan 0 vokasi. Kurangi jadi 2 pilihan "
                        f"atau ganti sebagian dengan prodi vokasi. Komposisi yang sah: {uraian}.",
                    )
                )
            else:
                temuan.append(
                    Temuan(
                        "komposisi_snbt_tidak_valid",
                        "pelanggaran",
                        f"Komposisi {k['akademik']} akademik + {k['vokasi']} vokasi "
                        f"(D3: {k['d3']}) belum sesuai ketentuan untuk {n} pilihan. "
                        f"Komposisi yang sah: {uraian}.",
                    )
                )

    # --- pilihan yang tidak dapat dinilai: dilaporkan, tidak dihitung dalam rasio ---
    gagal = [p.prodi_id for p in pilihan if p.status_gate == "tidak_memenuhi_syarat"]
    if gagal:
        temuan.append(
            Temuan(
                "pilihan_tidak_memenuhi_syarat",
                "peringatan",
                f"Tidak memenuhi syarat {aturan.jalur}: {_nama(pilihan, gagal)}. "
                "Pilihan ini tidak dihitung dalam komposisi.",
                prodi_ids=tuple(gagal),
            )
        )
    kurang = [
        p.prodi_id
        for p in pilihan
        if p.status_gate == "data_kurang"
        or (p.status_gate == "lolos" and p.kategori == "data_kurang")
    ]
    if kurang:
        temuan.append(
            Temuan(
                "pilihan_data_kurang",
                "info",
                f"Data belum lengkap untuk menilai: {_nama(pilihan, kurang)}. Lengkapi profil agar ikut dihitung.",
                prodi_ids=tuple(kurang),
            )
        )
    tanpa_acuan = [
        p.prodi_id for p in pilihan if p.status_gate == "lolos" and p.kategori == "belum_ada_acuan"
    ]
    if tanpa_acuan:
        temuan.append(
            Temuan(
                "pilihan_belum_ada_acuan",
                "info",
                f"Belum ada data acuan untuk: {_nama(pilihan, tanpa_acuan)}. Tidak dihitung dalam komposisi.",
                prodi_ids=tuple(tanpa_acuan),
            )
        )

    # --- heuristik komposisi (hanya bila cukup pilihan yang dapat dinilai) ---
    dinilai = k["reach"] + k["match"] + k["safe"]
    if dinilai >= aturan.min_pilihan_untuk_evaluasi:
        if k["safe"] < aturan.min_safe:
            temuan.append(
                Temuan(
                    "min_safe",
                    "peringatan",
                    f"Belum ada pilihan safe (minimal {aturan.min_safe}). Pertimbangkan satu pilihan "
                    "yang lebih aman sebagai cadangan.",
                )
            )
        if k["reach"] / dinilai > aturan.maks_rasio_reach:
            temuan.append(
                Temuan(
                    "maks_reach",
                    "peringatan",
                    f"{k['reach']} dari {dinilai} pilihan yang dinilai berkategori reach "
                    f"(batas maksimal {math.floor(aturan.maks_rasio_reach * dinilai + 1e-9)}). "
                    "Seimbangkan dengan pilihan match atau safe.",
                )
            )
    else:
        temuan.append(
            Temuan(
                "evaluasi_rasio_dilewati",
                "info",
                f"Aturan rasio reach/safe baru diterapkan bila ada minimal "
                f"{aturan.min_pilihan_untuk_evaluasi} pilihan yang dapat dinilai "
                f"(saat ini {dinilai}).",
            )
        )

    if aturan.peringatan_satu_ptn and n >= 2 and len({p.ptn_id for p in pilihan}) == 1:
        temuan.append(
            Temuan(
                "satu_ptn",
                "peringatan",
                f"Semua pilihan berada di satu PTN ({pilihan[0].ptn_nama}). "
                "Sebarkan ke beberapa PTN untuk mengurangi risiko.",
            )
        )

    # --- informasi ---
    if aturan.blokir_lintas_jalur:
        temuan.append(
            Temuan(
                "blokir_lintas_jalur",
                "info",
                "Peserta yang dinyatakan lulus SNBP tidak dapat mendaftar UTBK-SNBT maupun seleksi "
                "Mandiri di PTN mana pun. Lulus SNBP pada tahun siklus ini atau dua tahun sebelumnya "
                "juga menutup SNBT. Pertimbangkan ini saat menyusun kedua jalur.",
            )
        )
    if aturan.peringatan_satu_jalur and not ada_strategi_jalur_lain:
        lain = "SNBT" if aturan.jalur == "SNBP" else "SNBP"
        temuan.append(
            Temuan(
                "hanya_satu_jalur",
                "info",
                f"Baru pilihan {aturan.jalur} yang kamu susun. Pertimbangkan menyusun pilihan {lain} juga.",
            )
        )

    return urutkan(temuan)


def urutkan(temuan: Sequence[Temuan]) -> list[Temuan]:
    def kunci(t: Temuan) -> tuple[int, int]:
        idx = KODE_URUT.index(t.kode) if t.kode in KODE_URUT else len(KODE_URUT)
        return (TINGKAT_URUT[t.tingkat], idx)

    return sorted(temuan, key=kunci)


# ----------------------------------------------------------------------------- saran swap


def _unit_serius(temuan: Sequence[Temuan]) -> set[tuple[str, ...]]:
    """Unit masalah (pelanggaran + peringatan) untuk membandingkan sebelum/sesudah swap."""
    unit: set[tuple[str, ...]] = set()
    for t in temuan:
        if t.tingkat == "info":
            continue
        if t.kode in KODE_PER_PRODI:
            unit.update((t.kode, pid) for pid in t.prodi_ids)
        else:
            unit.add((t.kode,))
    return unit


def tambah_saran_swap(
    temuan: Sequence[Temuan],
    pilihan: Sequence[Pilihan],
    kandidat: Sequence[Pilihan],
    aturan: AturanStrategi,
    *,
    provinsi_sekolah: str | None,
    ada_strategi_jalur_lain: bool,
) -> list[Temuan]:
    """Isi `saran_swap` dari shortlist.

    Sebuah swap diterima hanya bila memperbaiki >= 1 masalah (pelanggaran/peringatan) TANPA
    menimbulkan masalah baru. Urutan deterministik: paling banyak memperbaiki, lalu urutan pilihan,
    lalu urutan shortlist.
    """
    awal = _unit_serius(temuan)
    if not awal or aturan.maks_saran_swap == 0:
        return list(temuan)

    dipilih = {p.prodi_id for p in pilihan}
    calon = [c for c in dict.fromkeys(kandidat) if c.prodi_id not in dipilih]
    saran: dict[tuple[str, ...], list[tuple[tuple[int, int, int], Saran]]] = {}
    for i, lama in enumerate(pilihan):
        for j, baru in enumerate(calon):
            susunan = [*pilihan[:i], baru, *pilihan[i + 1 :]]
            hasil = evaluasi(
                susunan,
                aturan,
                provinsi_sekolah=provinsi_sekolah,
                ada_strategi_jalur_lain=ada_strategi_jalur_lain,
            )
            sesudah = _unit_serius(hasil)
            diperbaiki = awal - sesudah
            if not diperbaiki or not sesudah <= awal:
                continue
            labels = sorted({LABEL_PERBAIKAN.get(u[0], u[0]) for u in diperbaiki})
            catatan_kategori = (
                f" {baru.nama} berkategori {baru.kategori} untukmu." if baru.dapat_dinilai else ""
            )
            s = Saran(
                lama.prodi_id,
                baru.prodi_id,
                f"Mengganti {lama.nama} ({lama.ptn_nama}) dengan {baru.nama} ({baru.ptn_nama}) "
                f"memperbaiki: {', '.join(labels)}.{catatan_kategori}",
            )
            urut = (-len(diperbaiki), i, j)
            for unit in diperbaiki:
                saran.setdefault(unit, []).append((urut, s))

    hasil_akhir: list[Temuan] = []
    for t in temuan:
        unit_t = _unit_serius([t])
        kumpul: dict[tuple[str, str], tuple[tuple[int, int, int], Saran]] = {}
        for u in unit_t:
            for urut, s in saran.get(u, []):
                kunci = (s.ganti, s.dengan)
                if kunci not in kumpul or urut < kumpul[kunci][0]:
                    kumpul[kunci] = (urut, s)
        terurut = [s for _, s in sorted(kumpul.values(), key=lambda x: x[0])]
        hasil_akhir.append(
            Temuan(
                t.kode,
                t.tingkat,
                t.pesan,
                t.prodi_ids,
                t.data_kurang,
                tuple(terurut[: aturan.maks_saran_swap]),
            )
        )
    return hasil_akhir
