"""Eksplorasi jurusan (FR-E1 sampai E3): rekomendasi rumpun dari minat dan nilai. Tanpa LLM.

Urutan kerja:
1. Profil tiap rumpun: dari data bila ada (prodi.tag_minat, prodi.mapel_penentu, tabel profesi),
   selain itu dari klasifikasi awal di config/app.yaml (ditandai belum diverifikasi).
2. Skor kecocokan deterministik (app.domain.match) dari minat dan rapor siswa.
3. Opsional: kelayakan (gate + penilaian, mesin yang sama dengan /analyze) bila `jalur` diminta.
Tidak ada penulisan ke DB.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.db import models as m
from app.domain.fields import PERTANYAAN
from app.domain.match import (
    alasan_template,
    dimensi_teratas,
    gabung_kecocokan,
    kemiripan_cosine,
    kesesuaian_nilai,
    mapel_terbaik,
)
from app.domain.ringkasan import rata_mapel
from app.services.analisis import analisis_banyak
from app.services.draf_eksplorasi import LABEL_DRAF, DrafEksplorasi
from app.services.refdata import RefData
from app.services.riasec import sumber_minat

SUMBER_DATA = "data"
SUMBER_DRAF = "draf"  # data/draft/*.csv: draf, belum terverifikasi
SUMBER_AWAL = "klasifikasi_awal"
SUMBER_TABEL_PROFESI = "tabel_profesi"
SUMBER_UMUM = "contoh_umum"


def _per_rumpun(db: Session) -> dict[str, list[tuple[m.Prodi, m.Ptn]]]:
    baris = db.execute(
        select(m.Prodi, m.Ptn).join(m.Ptn, m.Ptn.id == m.Prodi.ptn_id).order_by(m.Prodi.id)
    ).all()
    ada_data = set(db.execute(select(m.ProdiJalur.prodi_id).distinct()).scalars())
    per_rumpun: dict[str, list[tuple[m.Prodi, m.Ptn]]] = {}
    for p, t in baris:
        per_rumpun.setdefault(p.rumpun, []).append((p, t))
    for daftar in per_rumpun.values():  # prodi yang punya data keketatan lebih dulu, lalu urut id
        daftar.sort(key=lambda pt: (pt[0].id not in ada_data, pt[0].id))
    return per_rumpun


def _vektor_tag(bertag: Sequence[Sequence[str]]) -> dict[str, float]:
    hitung = Counter(t for tag in bertag for t in set(tag))
    return {d: hitung[d] / len(bertag) for d in sorted(hitung)}


def _profil_minat(
    daftar: Sequence[tuple[m.Prodi, m.Ptn]],
    dimensi: Sequence[str],
    awal: Mapping[str, float],
    draf: DrafEksplorasi | None = None,
) -> tuple[dict[str, float], str] | None:
    """Rata-rata vektor tag_minat prodi (bobot 1 per tag): data resmi, lalu draf, lalu klasifikasi awal."""
    kunci = set(dimensi)
    bertag = [t for t in ([x for x in (p.tag_minat or []) if x in kunci] for p, _ in daftar) if t]
    if bertag:
        return _vektor_tag(bertag), SUMBER_DATA
    if draf is not None:
        dtag = [
            t
            for t in ([x for x in draf.tag_minat.get(p.id, []) if x in kunci] for p, _ in daftar)
            if t
        ]
        if dtag:
            return _vektor_tag(dtag), SUMBER_DRAF
    return (dict(awal), SUMBER_AWAL) if awal else None


def _profil_mapel(
    daftar: Sequence[tuple[m.Prodi, m.Ptn]],
    awal: Mapping[str, float],
    draf: DrafEksplorasi | None = None,
) -> tuple[dict[str, float], str] | None:
    """Bobot mapel = frekuensi relatif mapel_penentu: data resmi, lalu draf, lalu klasifikasi awal."""
    hitung = Counter(mp for p, _ in daftar for mp in set(p.mapel_penentu or []))
    if hitung:
        puncak = max(hitung.values())
        return {mp: hitung[mp] / puncak for mp in sorted(hitung)}, SUMBER_DATA
    if draf is not None:
        hitung = Counter(mp for p, _ in daftar for mp in set(draf.mapel.get(p.id, [])))
        if hitung:
            puncak = max(hitung.values())
            return {mp: hitung[mp] / puncak for mp in sorted(hitung)}, SUMBER_DRAF
    return (dict(awal), SUMBER_AWAL) if awal else None


def _ptn_ringkas(daftar: Sequence[tuple[m.Prodi, m.Ptn]], maks: int) -> list[dict[str, Any]]:
    ptn: dict[str, dict[str, Any]] = {}
    for p, t in daftar[:maks]:
        ptn.setdefault(t.id, {"id": t.id, "nama": t.nama, "provinsi": t.provinsi, "prodi_ids": []})[
            "prodi_ids"
        ].append(p.id)
    return list(ptn.values())


def _profesi(db: Session) -> dict[str, list[str]]:
    hasil: dict[str, list[str]] = {}
    for p in db.execute(select(m.Profesi).order_by(m.Profesi.id)).scalars():
        hasil.setdefault(p.rumpun, []).append(p.nama)
    return hasil


def _kelayakan(
    db: Session,
    ref: RefData,
    config: AppConfig,
    profil: Mapping[str, Any],
    jalur: str,
    daftar: Sequence[tuple[m.Prodi, m.Ptn]],
) -> dict[str, Any]:
    dinilai = [p.id for p, _ in daftar[: config.explore.maks_prodi_kelayakan]]
    hasil = analisis_banyak(db, ref, config, profil, [(i, [jalur]) for i in dinilai])
    status = {h["gate"]["status"] for h in hasil}
    kategori = Counter(
        h["penilaian"]["kategori"] if h["penilaian"] else "tanpa_penilaian" for h in hasil
    )
    return {
        "jalur": jalur,
        "gate": next(iter(status)) if len(status) == 1 else "campuran",
        "jumlah_prodi_dinilai": len(dinilai),
        "dari_total_prodi": len(daftar),
        "kategori": {k: kategori[k] for k in sorted(kategori)},
        "data_kurang": sorted({d["field"] for h in hasil for d in h["data_kurang"]}),
        "indikatif": True,
    }


def jelajahi(
    db: Session,
    ref: RefData | None,
    config: AppConfig,
    profil: Mapping[str, Any],
    *,
    top_n: int,
    jalur: str | None,
    sesi_id: uuid.UUID | None = None,
    draf: DrafEksplorasi | None = None,
) -> dict[str, Any]:
    cfg = config.explore
    # Hanya PENANDA asal/keyakinan minat; tidak memengaruhi skor atau urutan rekomendasi.
    asal_minat = (
        sumber_minat(db, sesi_id, profil.get("minat"))
        if sesi_id is not None
        else {"sumber": "manual", "keyakinan": None, "alasan": []}
    )
    dimensi = config.minat.dimensi
    minat_siswa = {
        d: float(v)
        for d, v in (profil.get("minat") or {}).items()
        if v is not None and d in dimensi
    }
    minat_ada = any(v > 0 for v in minat_siswa.values())

    per_rumpun = _per_rumpun(db)
    profesi_db = _profesi(db)
    kandidat: list[dict[str, Any]] = []
    rapor_ada = False

    for rumpun in sorted(per_rumpun):
        daftar = per_rumpun[rumpun]
        awal = cfg.rumpun.get(rumpun)
        minat_r = _profil_minat(daftar, dimensi, awal.minat if awal else {}, draf)
        mapel_r = _profil_mapel(daftar, awal.mapel if awal else {}, draf)
        if minat_r is None and mapel_r is None:
            continue  # tidak ada profil sama sekali: tidak bisa dinilai, tidak ditebak

        skor_minat = kemiripan_cosine(minat_siswa, minat_r[0]) if minat_r and minat_ada else None
        nilai = kesesuaian_nilai(
            rata_mapel(profil, list(mapel_r[0])) if mapel_r else {}, mapel_r[0] if mapel_r else {}
        )
        rapor_ada = rapor_ada or nilai.skor is not None
        skor, bobot = gabung_kecocokan(skor_minat, nilai.skor, cfg.bobot.minat, cfg.bobot.nilai)
        if skor is None:
            continue

        if rumpun in profesi_db:
            contoh, sumber_profesi = profesi_db[rumpun][: cfg.maks_profesi], SUMBER_TABEL_PROFESI
        elif draf is not None and rumpun in draf.profesi:
            contoh, sumber_profesi = draf.profesi[rumpun][: cfg.maks_profesi], SUMBER_DRAF
        else:
            contoh, sumber_profesi = (awal.profesi[: cfg.maks_profesi] if awal else []), SUMBER_UMUM

        sumber_profil = {
            "minat": minat_r[1] if minat_r else None,
            "mapel": mapel_r[1] if mapel_r else None,
            "profesi": sumber_profesi,
        }

        kandidat.append(
            {
                "rumpun": rumpun,
                "skor_kecocokan": round(skor, 2),
                "komponen": {
                    "minat": None if skor_minat is None else round(skor_minat, 2),
                    "nilai": None if nilai.skor is None else round(nilai.skor, 2),
                },
                "bobot_efektif": {k: round(v, 2) for k, v in bobot.items()},
                "alasan": alasan_template(
                    dimensi=dimensi_teratas(minat_siswa, minat_r[0])
                    if minat_r and minat_ada
                    else [],
                    terbaik=mapel_terbaik(nilai.dipakai, mapel_r[0]) if mapel_r else None,
                    mapel_kosong=nilai.kosong if mapel_r else [],
                    minat_diisi=minat_ada,
                ),
                "mapel_belum_diisi": nilai.kosong,
                "keyakinan_minat": asal_minat["keyakinan"] if skor_minat is not None else None,
                "contoh_profesi": contoh,
                "sumber_profil": sumber_profil,
                "label_data": LABEL_DRAF if SUMBER_DRAF in sumber_profil.values() else None,
                "total_prodi": len(daftar),
                "prodi_ids": [p.id for p, _ in daftar[: cfg.maks_prodi_per_rumpun]],
                "ptn": _ptn_ringkas(daftar, cfg.maks_prodi_per_rumpun),
                "kelayakan": _kelayakan(db, ref, config, profil, jalur, daftar)
                if jalur and ref is not None
                else None,
            }
        )

    # Urut menurut skor yang DITAMPILKAN (2 desimal), lalu nama rumpun: skor sama selalu urut alfabet.
    kandidat.sort(key=lambda r: (-r["skor_kecocokan"], r["rumpun"]))
    rekomendasi = kandidat[:top_n]

    # Fallback penelusuran katalog: rumpun yang tidak bisa diberi skor (tanpa profil, atau minat dan
    # nilai belum diisi) tetap ditampilkan apa adanya, tanpa skor dan tanpa tebakan.
    dinilai = {r["rumpun"] for r in kandidat}
    penelusuran = [
        {
            "rumpun": rumpun,
            "total_prodi": len(per_rumpun[rumpun]),
            "prodi_ids": [p.id for p, _ in per_rumpun[rumpun][: cfg.maks_prodi_per_rumpun]],
            "ptn": _ptn_ringkas(per_rumpun[rumpun], cfg.maks_prodi_per_rumpun),
        }
        for rumpun in sorted(per_rumpun)
        if rumpun not in dinilai
    ]

    data_kurang = []
    if not minat_ada:
        data_kurang.append({"field": "minat", "pertanyaan": PERTANYAAN["minat"]})
    if not rapor_ada:
        data_kurang.append({"field": "nilai_rapor", "pertanyaan": PERTANYAAN["nilai_rapor"]})

    catatan = [
        "Skor kecocokan hanya menunjukkan kemiripan minat dan nilai dengan rumpun. Ini bukan "
        "prediksi cocok atau tidak cocok, dan bukan peluang diterima.",
    ]
    if any(
        SUMBER_AWAL in r["sumber_profil"].values() or SUMBER_UMUM in r["sumber_profil"].values()
        for r in rekomendasi
    ):
        catatan.append(
            "Profil rumpun (minat, mapel relevan, contoh profesi) masih klasifikasi awal dan belum "
            "diverifikasi tim data."
        )
    if any(SUMBER_DRAF in r["sumber_profil"].values() for r in rekomendasi):
        catatan.append(
            f"Sebagian profil rumpun (minat, mapel, atau contoh profesi) berasal dari data {LABEL_DRAF}. "
            "Perlakukan sebagai gambaran awal, bukan data resmi."
        )
    if penelusuran:
        catatan.append(
            "Rumpun di penelusuran_katalog belum bisa diberi skor (profil rumpun atau data minat dan "
            "nilai belum cukup), jadi hanya ditampilkan sebagai penelusuran katalog tanpa skor."
        )
    if asal_minat["keyakinan"] == "rendah" and rekomendasi:
        catatan.append(
            "Minat berasal dari tes minat dengan keyakinan rendah ("
            + "; ".join(asal_minat["alasan"])
            + "). Anggap sisi minat pada rekomendasi ini kurang dapat diandalkan; ulangi tes atau "
            "lengkapi jawabanmu."
        )
    if jalur is None and rekomendasi:
        catatan.append("Sertakan jalur (SNBP atau SNBT) untuk melihat kelayakan tiap rumpun.")
    if jalur and rekomendasi:
        catatan.append(
            "Kelayakan memakai mesin aturan yang sama dengan analisis target dan bersifat indikatif."
        )

    return {
        "rekomendasi": rekomendasi,
        "data_kurang": data_kurang,
        "jalur": jalur,
        "indikatif": True,
        "minat_sumber": asal_minat,
        "memakai_data_draf": any(SUMBER_DRAF in r["sumber_profil"].values() for r in rekomendasi),
        "penelusuran_katalog": penelusuran,
        "catatan": catatan,
    }
