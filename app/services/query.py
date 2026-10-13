"""POST /query: RAG bersitasi, penjelasan hasil mesin aturan, dan jawaban keputusan dari mesin aturan.

Prinsip (PRD 7.7, 8.5):
- Konteks profil/hasil dibangun SERVER dari id + data sesi; klien tidak pernah mengirimnya.
- Pertanyaan keputusan dijawab dari mesin aturan, bukan opini LLM.
- Retrieval di bawah ambang -> `yakin: false` TANPA memanggil LLM.
- `sumber[]` dibangun dari metadata chunk/sumber data, bukan dari teks keluaran LLM.
- LLM/embedding gagal -> teks cadangan + `fallback: true`, bukan 5xx.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.errors import AppError
from app.db import models as m
from app.domain.intent import adalah_pertanyaan_keputusan
from app.llm.fallback_texts import (
    TEKS_JELASKAN_PENGANTAR,
    TEKS_KEPUTUSAN_TANPA_KONTEKS,
    TEKS_LAYANAN_GAGAL,
    TEKS_TIDAK_YAKIN,
    penjelasan_dari_hasil,
)
from app.llm.guard import angka_tidak_dikenal, keluaran_aman
from app.llm.pii import normalisasi_pertanyaan, saring_pii
from app.llm.prompts import (
    SISTEM_JELASKAN,
    SISTEM_RAG,
    ChunkKonteks,
    JawabanRAG,
    prompt_jelaskan,
    prompt_rag,
)
from app.llm.service import LLMService
from app.rag.retrieve import HasilCari, cari, di_atas_ambang
from app.schemas.query import QueryRequest
from app.services import profile
from app.services.analisis import analisis_satu, muat_target
from app.services.querylog import catat
from app.services.refdata import RefDataProvider
from app.services.sessions import SesiAktif

log = logging.getLogger("jalurku.query")

JUDUL_SUMBER = {
    "rules_gate": "Ketentuan resmi SNPMB (syarat jalur)",
    "keketatan": "Data daya tampung dan peminat prodi",
    "acuan_skor": "Acuan skor tahun lalu",
}
MAKS_SARAN_PANJANG = 150


# ----------------------------------------------------------------------------- bentuk respons


def _respons(
    jawaban: str,
    *,
    jenis: str,
    mode: str,
    yakin: bool,
    sumber: Sequence[Mapping[str, Any]] = (),
    data_dibutuhkan: Sequence[Mapping[str, str]] = (),
    saran: Sequence[str] = (),
    fallback: bool = False,
    catatan: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "jawaban": jawaban,
        "sumber": [dict(s) for s in sumber],
        "yakin": yakin,
        "data_dibutuhkan": [dict(d) for d in data_dibutuhkan],
        "saran_pertanyaan": list(saran),
        "fallback": fallback,
        "mode": mode,
        "jenis_jawaban": jenis,
        "catatan": list(catatan),
    }


def sumber_dari_hasil(hasil: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Sumber dari data mesin aturan (rules, keketatan, acuan), dedupe per URL."""
    keluar: dict[str, dict[str, Any]] = {}
    for s in hasil["sumber_detail"]:
        if s["url"] and s["url"] not in keluar:
            keluar[s["url"]] = {
                "judul": JUDUL_SUMBER.get(s["jenis"], s["jenis"]),
                "url": s["url"],
                "halaman": None,
            }
    return list(keluar.values())


def sumber_dari_chunk(
    chunks: Sequence[HasilCari], *, per_dokumen: bool = False
) -> list[dict[str, Any]]:
    """Sitasi dari METADATA chunk (judul, url, halaman), bukan dari teks LLM."""
    keluar: dict[tuple, dict[str, Any]] = {}
    for c in chunks:
        kunci = (c.url, None if per_dokumen else c.halaman)
        if kunci not in keluar:
            keluar[kunci] = {
                "judul": c.judul,
                "url": c.url,
                "halaman": None if per_dokumen else c.halaman,
            }
    return list(keluar.values())


def sumber_resmi(db: Session, batas: int = 3) -> list[dict[str, Any]]:
    baris = db.execute(
        select(m.DokumenSumber)
        .where(m.DokumenSumber.jenis.ilike("%resmi%"))
        .order_by(m.DokumenSumber.tahun_siklus.desc(), m.DokumenSumber.id)
        .limit(batas)
    ).scalars()
    return [{"judul": d.judul, "url": d.url, "halaman": None} for d in baris]


def fakta_dari_hasil(hasil: Mapping[str, Any]) -> dict[str, Any]:
    """Ringkas hasil mesin aturan menjadi fakta kecil untuk LLM. Hanya angka/status dari mesin aturan."""
    p = hasil.get("penilaian")
    penilaian = None
    if p:
        penilaian = {
            k: p.get(k)
            for k in (
                "kategori",
                "metode",
                "indikatif",
                "label",
                "keyakinan",
                "alasan",
                "gap",
                "catatan",
                "acuan",
            )
        }
        if p.get("tier"):
            penilaian["tier"] = {k: p["tier"].get(k) for k in ("nilai", "skor", "sumber")}
        if p.get("pita"):
            penilaian["pita"] = {k: p["pita"].get(k) for k in ("nilai", "rasio", "tahun_peminat")}
    return {
        "prodi": {k: hasil["prodi"][k] for k in ("nama", "ptn_nama", "jenjang", "program")},
        "jalur": hasil["jalur"],
        "gate": {
            "status": hasil["gate"]["status"],
            "syarat": [
                {
                    "id": s["id"],
                    "status": s["status"],
                    **({"alasan": s["alasan"]} if s["status"] == "gagal" else {}),
                }
                for s in hasil["gate"]["syarat"]
            ],
        },
        "penilaian": penilaian,
        "data_kurang": [d["pertanyaan"] for d in hasil["data_kurang"]],
        "catatan": hasil["catatan"],
        "status_verifikasi": hasil["status_verifikasi"],
    }


# ----------------------------------------------------------------------------- util


def _saran(config: AppConfig, pertanyaan: str, dari_llm: Sequence[str] = ()) -> list[str]:
    ini = normalisasi_pertanyaan(pertanyaan)
    kandidat: list[str] = []
    for s in [*dari_llm, *config.rag.saran_pertanyaan]:
        s = " ".join(str(s).split())
        if not s or len(s) > MAKS_SARAN_PANJANG or saring_pii(s).ada:
            continue
        if normalisasi_pertanyaan(s) == ini or s in kandidat:
            continue
        kandidat.append(s)
    return kandidat[: config.query.maks_saran_pertanyaan]


def _data_dibutuhkan(hasil: Mapping[str, Any]) -> list[dict[str, str]]:
    return [{"field": d["field"], "pertanyaan": d["pertanyaan"]} for d in hasil["data_kurang"]]


def _hash_teks(teks: str) -> str:
    return hashlib.sha1(teks.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - bukan untuk keamanan


def _analisis_konteks(
    db: Session, refdata: RefDataProvider, config: AppConfig, sesi: SesiAktif, body: QueryRequest
) -> dict[str, Any]:
    """Hasil mesin aturan untuk konteks (prodi, jalur) + override terstruktur. Dibangun server dari id."""
    k = body.konteks
    assert k is not None and k.prodi_id and k.jalur
    ref = refdata.get(db)
    dimuat = muat_target(db, [k.prodi_id])
    dasar = profile.baca_profil(db, sesi.id)
    patch = k.override.model_dump(exclude_unset=True) if k.override is not None else {}
    profil = profile.profil_gabungan(db, dasar, patch, config, ref)  # tidak ditulis ke DB
    return analisis_satu(db, ref, config, profil, dimuat[k.prodi_id], k.jalur)


# ----------------------------------------------------------------------------- cabang jawaban


def _jelaskan(
    db: Session,
    llm: LLMService,
    refdata: RefDataProvider,
    config: AppConfig,
    sesi: SesiAktif,
    body: QueryRequest,
    q: str,
) -> tuple[dict[str, Any], list[int]]:
    """Mode 'jelaskan' (tombol 'Kenapa?'): LLM hanya menjelaskan hasil mesin aturan untuk pasangan itu."""
    hasil = _analisis_konteks(db, refdata, config, sesi, body)
    fakta = fakta_dari_hasil(hasil)
    cadangan = TEKS_JELASKAN_PENGANTAR + penjelasan_dari_hasil(hasil)
    g = llm.generate(
        db,
        namespace="jelaskan",
        system=SISTEM_JELASKAN,
        prompt=prompt_jelaskan(q, fakta),
        kunci_cache={"fakta": fakta, "q": normalisasi_pertanyaan(q)},
        max_output_tokens=512,
    )
    teks, fallback = g.teks, g.fallback
    if teks is not None:
        aman, alasan = keluaran_aman(teks, fakta)
        if not aman:
            log.warning("penjelasan LLM ditolak pagar keluaran: %s", alasan)
            teks, fallback = None, True
    return (
        _respons(
            teks if teks is not None else cadangan,
            jenis="penjelasan",
            mode="jelaskan",
            yakin=teks is not None,
            sumber=sumber_dari_hasil(hasil),
            data_dibutuhkan=_data_dibutuhkan(hasil),
            saran=_saran(config, q),
            fallback=fallback,
        ),
        [],
    )


def _keputusan(
    db: Session,
    refdata: RefDataProvider,
    config: AppConfig,
    sesi: SesiAktif,
    body: QueryRequest,
    q: str,
) -> tuple[dict[str, Any], list[int]]:
    """Pertanyaan keputusan: dijawab dari hasil mesin aturan, tanpa memanggil LLM (FR-Q5)."""
    k = body.konteks
    if k is None or not (k.prodi_id and k.jalur):
        kurang = []
        if k is None or not k.prodi_id:
            kurang.append(
                {"field": "konteks.prodi_id", "pertanyaan": "Prodi mana yang ingin kamu cek?"}
            )
        if k is None or not k.jalur:
            kurang.append(
                {
                    "field": "konteks.jalur",
                    "pertanyaan": "Jalur apa yang ingin kamu cek, SNBP atau SNBT?",
                }
            )
        return (
            _respons(
                TEKS_KEPUTUSAN_TANPA_KONTEKS,
                jenis="mesin_aturan",
                mode="tanya",
                yakin=False,
                sumber=sumber_resmi(db),
                data_dibutuhkan=kurang,
                saran=_saran(config, q),
            ),
            [],
        )
    hasil = _analisis_konteks(db, refdata, config, sesi, body)
    pasti = hasil["gate"]["status"] != "data_kurang" and not hasil["data_kurang"]
    jawaban = (
        "Keputusan syarat dan kategori berasal dari mesin aturan di aplikasi, bukan opini AI. "
        + penjelasan_dari_hasil(hasil)
    )
    return (
        _respons(
            jawaban,
            jenis="mesin_aturan",
            mode="tanya",
            yakin=pasti,
            sumber=sumber_dari_hasil(hasil),
            data_dibutuhkan=_data_dibutuhkan(hasil),
            saran=_saran(config, q),
        ),
        [],
    )


def _rag(
    db: Session,
    llm: LLMService,
    refdata: RefDataProvider,
    config: AppConfig,
    sesi: SesiAktif,
    body: QueryRequest,
    q: str,
) -> tuple[dict[str, Any], list[int]]:
    k = body.konteks
    data_dibutuhkan: list[dict[str, str]] = []
    if k is not None and k.prodi_id and k.jalur:  # konteks opsional: hanya untuk pertanyaan balik
        data_dibutuhkan = _data_dibutuhkan(_analisis_konteks(db, refdata, config, sesi, body))

    def balas(
        jawaban: str, *, yakin: bool, sumber, saran=(), fallback=False, jenis="rag"
    ) -> dict[str, Any]:
        return _respons(
            jawaban,
            jenis=jenis,
            mode="tanya",
            yakin=yakin,
            sumber=sumber,
            data_dibutuhkan=data_dibutuhkan,
            saran=saran or _saran(config, q),
            fallback=fallback,
        )

    emb = llm.embed_pertanyaan(db, q)
    if emb.fallback or emb.vektor is None:
        return balas(
            TEKS_LAYANAN_GAGAL,
            yakin=False,
            sumber=sumber_resmi(db),
            fallback=True,
            jenis="tidak_yakin",
        ), []

    ditemukan = cari(db, emb.vektor, top_k=config.rag.top_k, embedding_model=config.embedding.model)
    konteks = di_atas_ambang(ditemukan, config.rag.ambang_skor)
    if not konteks:  # di bawah ambang: yakin=false TANPA memanggil LLM
        terkait = (
            sumber_dari_chunk(ditemukan[:2], per_dokumen=True) if ditemukan else sumber_resmi(db)
        )
        return balas(TEKS_TIDAK_YAKIN, yakin=False, sumber=terkait, jenis="tidak_yakin"), []

    ids = [c.chunk_id for c in konteks]
    g = llm.generate(
        db,
        namespace="rag",
        system=SISTEM_RAG,
        prompt=prompt_rag(
            q, [ChunkKonteks(i, c.judul, c.halaman, c.teks) for i, c in enumerate(konteks, 1)]
        ),
        kunci_cache={
            "q": normalisasi_pertanyaan(q),
            "chunks": [[c.chunk_id, _hash_teks(c.teks)] for c in konteks],
        },
        json_schema=JawabanRAG,
    )
    sumber = sumber_dari_chunk(konteks)
    if g.teks is None:
        return balas(
            TEKS_LAYANAN_GAGAL, yakin=False, sumber=sumber, fallback=True, jenis="tidak_yakin"
        ), ids
    try:
        jawab = JawabanRAG.model_validate_json(g.teks)
    except ValidationError:
        log.warning("keluaran LLM bukan JSON sesuai skema")
        return balas(
            TEKS_LAYANAN_GAGAL, yakin=False, sumber=sumber, fallback=True, jenis="tidak_yakin"
        ), ids

    if not jawab.cukup_informasi or not jawab.jawaban.strip():
        return balas(TEKS_TIDAK_YAKIN, yakin=False, sumber=sumber, jenis="tidak_yakin"), ids
    asing = angka_tidak_dikenal(
        jawab.jawaban, {"konteks": [c.teks for c in konteks], "pertanyaan": q}
    )
    if asing:  # angka yang tidak ada di dokumen = berisiko halusinasi
        log.warning("jawaban LLM ditolak: angka di luar konteks")
        return balas(TEKS_TIDAK_YAKIN, yakin=False, sumber=sumber, jenis="tidak_yakin"), ids
    return balas(
        jawab.jawaban.strip(),
        yakin=True,
        sumber=sumber,
        saran=_saran(config, q, jawab.saran_pertanyaan),
    ), ids


# ----------------------------------------------------------------------------- titik masuk


def jawab(
    db: Session,
    *,
    llm: LLMService,
    refdata: RefDataProvider,
    config: AppConfig,
    sesi: SesiAktif,
    body: QueryRequest,
) -> dict[str, Any]:
    kurang = body.field_wajib_kurang()
    if kurang:
        raise AppError(
            "validasi_gagal",
            "Data yang dikirim tidak valid",
            status_code=422,
            detail={
                "field": [
                    {"field": f, "pesan": "wajib untuk mode 'jelaskan'", "tipe": "missing"}
                    for f in kurang
                ]
            },
        )
    pii = saring_pii(body.pertanyaan)
    q = pii.teks  # hanya teks tersaring yang dicatat, di-cache, atau dikirim ke LLM

    if body.mode == "jelaskan":
        respons, ids = _jelaskan(db, llm, refdata, config, sesi, body, q)
    elif adalah_pertanyaan_keputusan(
        q, config.query.pola_keputusan, config.query.pengecualian_keputusan
    ):
        respons, ids = _keputusan(db, refdata, config, sesi, body, q)
    else:
        respons, ids = _rag(db, llm, refdata, config, sesi, body, q)

    if pii.ada:
        respons["catatan"].append(
            "Pertanyaanmu memuat data pribadi ("
            + ", ".join(pii.ditemukan)
            + "). Bagian itu disamarkan dan tidak dikirim ke AI."
        )
    catat(db, sesi.id, q, yakin=respons["yakin"], sumber_ids=ids)
    return respons
