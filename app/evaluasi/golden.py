"""Evaluasi golden set (PRD bagian 14): akurasi gate, kesesuaian persona, dan kualitas RAG.

Pustaka ini hanya MENGUKUR. Ia tidak pernah mengisi `terakhir_diverifikasi` atau menandai apa pun
sebagai terverifikasi. Pengukuran otomatis RAG adalah proksi (sumber, halaman, angka kunci); akurasi
jawaban yang sebenarnya tetap dinilai manusia (kolom `nilai_manual` di laporan).

`client` adalah httpx.Client atau Starlette TestClient yang menuju aplikasi JalurKu.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR
from app.core.errors import AppError
from app.domain.gate import evaluasi_gate
from app.schemas.profile import ProfilePatch
from app.services import persona as modul_persona
from app.services.persona import Persona
from app.services.refdata import muat_refdata

API = "/api/v1"
GOLDEN_GATE = ROOT_DIR / "config" / "golden" / "gate.json"
GOLDEN_RAG_CSV = ROOT_DIR / "data" / "seed" / "golden_set.csv"
CONSENT = {"consent": True, "consent_version": "golden-set"}

# Syarat minimal golden set RAG (PRD bagian 14)
MIN_SOAL = 20
MIN_DI_LUAR_CAKUPAN = 5
MIN_KEPUTUSAN = 3


class GoldenError(ValueError):
    """Berkas golden tidak valid."""


@dataclass
class Hasil:
    id: str
    ok: bool
    detail: str = ""


# =============================================================================== gate


class HarapanKasus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: Literal["lolos", "tidak_memenuhi_syarat", "data_kurang"]
    penilaian: Literal["ada", "null"]
    syarat: dict[str, Literal["lolos", "gagal", "data_kurang", "tidak_berlaku"]] = Field(
        default_factory=dict
    )


class KasusGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    deskripsi: str
    dasar: str  # id persona yang profilnya menjadi dasar
    jalur: Literal["SNBP", "SNBT"]
    prodi_id: str = "ui-ilmu-komputer"
    sumber_aturan: str
    override: dict[str, Any]
    harapan: HarapanKasus
    terakhir_diverifikasi: date | None = None
    diverifikasi_oleh: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> KasusGate:
        try:
            ProfilePatch.model_validate(self.override)
        except ValidationError as exc:
            e = exc.errors()[0]
            raise ValueError(
                f"override tidak valid ({'.'.join(map(str, e['loc']))}: {e['msg']})"
            ) from exc
        if bool(self.terakhir_diverifikasi) != bool(self.diverifikasi_oleh):
            raise ValueError("terakhir_diverifikasi dan diverifikasi_oleh harus diisi bersamaan")
        return self

    @property
    def terverifikasi(self) -> bool:
        return self.terakhir_diverifikasi is not None


class BerkasGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versi: int
    catatan: str
    kasus: list[KasusGate]

    @model_validator(mode="after")
    def _id_unik(self) -> BerkasGate:
        ids = [k.id for k in self.kasus]
        ganda = sorted({i for i in ids if ids.count(i) > 1})
        if ganda:
            raise ValueError(f"id kasus ganda: {', '.join(ganda)}")
        return self


def muat_kasus_gate(path: Path = GOLDEN_GATE) -> list[KasusGate]:
    try:
        return BerkasGate.model_validate(json.loads(path.read_text(encoding="utf-8"))).kasus
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenError(f"{path.name}: tidak bisa dibaca ({type(exc).__name__})") from exc
    except ValidationError as exc:
        e = exc.errors()[0]
        raise GoldenError(f"{path.name}: {'.'.join(map(str, e['loc']))}: {e['msg']}") from exc


class SesiEvaluasi:
    """Sesi sementara untuk evaluasi; selalu dihapus (tidak ada data persona yang tertinggal)."""

    def __init__(self, client) -> None:
        self.client = client
        self._header: list[dict[str, str]] = []

    def buka(self, profil: dict[str, Any] | None = None) -> dict[str, str]:
        r = self.client.post(f"{API}/session", json=CONSENT)
        if r.status_code != 201:
            raise GoldenError(f"POST /session gagal ({r.status_code}): {r.text[:200]}")
        header = {"Authorization": f"Bearer {r.json()['token']}"}
        self._header.append(header)
        if profil:
            r = self.client.put(f"{API}/profile", json=profil, headers=header)
            if r.status_code != 200:
                raise GoldenError(f"PUT /profile gagal ({r.status_code}): {r.text[:200]}")
        return header

    def tutup(self) -> None:
        for h in self._header:
            self.client.delete(f"{API}/session", headers=h)
        self._header.clear()

    def __enter__(self) -> SesiEvaluasi:
        return self

    def __exit__(self, *_: object) -> None:
        self.tutup()


def jalankan_kasus_gate(client, kasus: Sequence[KasusGate]) -> list[Hasil]:
    hasil: list[Hasil] = []
    with SesiEvaluasi(client) as sesi:
        header_per_dasar: dict[str, dict[str, str]] = {}
        for k in kasus:
            try:
                if k.dasar not in header_per_dasar:
                    header_per_dasar[k.dasar] = sesi.buka(modul_persona.muat(k.dasar).profil)
                body = {
                    "targets": [{"prodi_id": k.prodi_id, "jalur": [k.jalur]}],
                    "override": k.override,
                }
                r = client.post(f"{API}/analyze", json=body, headers=header_per_dasar[k.dasar])
                if r.status_code != 200:
                    hasil.append(Hasil(k.id, False, f"/analyze {r.status_code}: {r.text[:150]}"))
                    continue
                hasil.append(_bandingkan_kasus(k, r.json()["hasil"][0]))
            except (GoldenError, modul_persona.PersonaError, KeyError, IndexError) as exc:
                hasil.append(Hasil(k.id, False, f"{type(exc).__name__}: {exc}"))
    return hasil


def _bandingkan_kasus(k: KasusGate, h: dict[str, Any]) -> Hasil:
    selisih: list[str] = []
    if h["gate"]["status"] != k.harapan.gate:
        selisih.append(f"gate {h['gate']['status']} (harapan {k.harapan.gate})")
    ada = "null" if h["penilaian"] is None else "ada"
    if ada != k.harapan.penilaian:
        selisih.append(f"penilaian {ada} (harapan {k.harapan.penilaian})")
    status_syarat = {s["id"]: s["status"] for s in h["gate"]["syarat"]}
    for sid, harap in k.harapan.syarat.items():
        if status_syarat.get(sid) != harap:
            selisih.append(f"{sid} {status_syarat.get(sid)} (harapan {harap})")
    return Hasil(k.id, not selisih, "; ".join(selisih))


# =============================================================================== persona


def jalankan_persona(client, db: Session, persona: Persona) -> list[Hasil]:
    """Gate umum persona (domain, tanpa syarat khusus prodi) dan kategori pilihan demo (API)."""
    hasil: list[Hasil] = []
    try:
        ref = muat_refdata(db)
    except AppError as exc:  # DB belum berisi ketentuan: laporkan, jangan melempar
        return [
            Hasil(f"persona:{persona.id}:gate:{jalur}", False, f"{exc.pesan} (jalankan ingest)")
            for jalur in persona.harapan.gate
        ]
    for jalur, harap in persona.harapan.gate.items():
        rid = f"persona:{persona.id}:gate:{jalur}"
        if jalur not in ref.rules:
            hasil.append(Hasil(rid, False, f"rules {jalur} tidak ada di DB (ingest belum jalan?)"))
            continue
        aktual = evaluasi_gate(ref.rules[jalur], persona.profil, ref.ketentuan).status
        hasil.append(Hasil(rid, aktual == harap, "" if aktual == harap else f"{aktual} != {harap}"))

    if persona.harapan.penilaian:
        with SesiEvaluasi(client) as sesi:
            header = sesi.buka(persona.profil)
            for jalur, peta in persona.harapan.penilaian.items():
                body = {"targets": [{"prodi_id": p, "jalur": [jalur]} for p in peta]}
                r = client.post(f"{API}/analyze", json=body, headers=header)
                if r.status_code != 200:
                    hasil.append(
                        Hasil(f"persona:{persona.id}:penilaian:{jalur}", False, f"{r.status_code}")
                    )
                    continue
                for h in r.json()["hasil"]:
                    p = h["penilaian"]
                    aktual = p["kategori"] if p else "tanpa_penilaian"
                    harap = peta[h["prodi_id"]]
                    hasil.append(
                        Hasil(
                            f"persona:{persona.id}:penilaian:{jalur}:{h['prodi_id']}",
                            aktual == harap,
                            "" if aktual == harap else f"{aktual} != {harap}",
                        )
                    )
    return hasil


# =============================================================================== RAG

TipeSoal = Literal["dalam_cakupan", "di_luar_cakupan", "keputusan"]
_TIPE = {
    "dalam cakupan": "dalam_cakupan",
    "di luar cakupan": "di_luar_cakupan",
    "keputusan": "keputusan",
}
_ANGKA = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class SoalRag:
    nomor: int
    pertanyaan: str
    jawaban_benar: str
    sumber_url: str | None
    halaman: int | None
    tipe: TipeSoal


def muat_soal_rag(path: Path = GOLDEN_RAG_CSV) -> list[SoalRag]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            baris = list(csv.DictReader(f))
    except OSError as exc:
        raise GoldenError(f"{path.name}: tidak bisa dibaca ({type(exc).__name__})") from exc
    soal: list[SoalRag] = []
    for no, b in enumerate(baris, start=1):
        tipe = _TIPE.get((b.get("tipe") or "").strip().lower())
        pertanyaan = (b.get("pertanyaan") or "").strip()
        if tipe is None or not pertanyaan:
            raise GoldenError(f"{path.name} baris {no}: pertanyaan kosong atau tipe tidak dikenal")
        hal = (b.get("halaman") or "").strip()
        if hal and not hal.isdigit():
            raise GoldenError(f"{path.name} baris {no}: halaman harus angka")
        soal.append(
            SoalRag(
                no,
                pertanyaan,
                (b.get("jawaban_benar") or "").strip(),
                (b.get("sumber_url") or "").strip() or None,
                int(hal) if hal else None,
                tipe,  # type: ignore[arg-type]
            )
        )
    return soal


def periksa_kecukupan(soal: Sequence[SoalRag]) -> list[str]:
    """Kekurangan golden set terhadap syarat PRD. Kosong = memenuhi syarat minimal."""
    kurang: list[str] = []
    if len(soal) < MIN_SOAL:
        kurang.append(f"hanya {len(soal)} pertanyaan (minimal {MIN_SOAL})")
    luar = sum(s.tipe == "di_luar_cakupan" for s in soal)
    if luar < MIN_DI_LUAR_CAKUPAN:
        kurang.append(f"hanya {luar} pertanyaan di luar cakupan (minimal {MIN_DI_LUAR_CAKUPAN})")
    putusan = sum(s.tipe == "keputusan" for s in soal)
    if putusan < MIN_KEPUTUSAN:
        kurang.append(f"hanya {putusan} pertanyaan keputusan (minimal {MIN_KEPUTUSAN})")
    tanpa_halaman = sum(s.tipe == "dalam_cakupan" and s.halaman is None for s in soal)
    if tanpa_halaman:
        kurang.append(f"{tanpa_halaman} pertanyaan dalam cakupan belum diisi halamannya")
    tanpa_sumber = sum(s.tipe == "dalam_cakupan" and not s.sumber_url for s in soal)
    if tanpa_sumber:
        kurang.append(f"{tanpa_sumber} pertanyaan dalam cakupan tanpa sumber_url")
    return kurang


@dataclass
class HasilRag:
    soal: SoalRag
    jawaban: str = ""
    yakin: bool | None = None
    jenis_jawaban: str = ""
    fallback: bool | None = None
    sumber: list[dict[str, Any]] = field(default_factory=list)
    sumber_cocok: bool | None = None
    halaman_cocok: bool | None = None
    angka_cocok: bool | None = None
    lulus_otomatis: bool = False
    catatan: str = ""


def _norm_url(url: str) -> str:
    return unquote(url).strip().rstrip("/").lower()


def _angka(teks: str) -> set[str]:
    return {a.replace(",", ".") for a in _ANGKA.findall(teks)}


def nilai_satu(soal: SoalRag, respons: dict[str, Any] | None, status: int = 200) -> HasilRag:
    """Skor otomatis satu pertanyaan. Untuk 'dalam cakupan' ini proksi, bukan akurasi jawaban."""
    h = HasilRag(soal)
    if respons is None:
        h.catatan = f"/query gagal (HTTP {status})"
        return h
    h.jawaban = respons.get("jawaban", "")
    h.yakin = respons.get("yakin")
    h.jenis_jawaban = respons.get("jenis_jawaban", "")
    h.fallback = respons.get("fallback")
    h.sumber = respons.get("sumber") or []

    if soal.tipe == "di_luar_cakupan":
        h.lulus_otomatis = h.yakin is False  # kejujuran: tidak boleh yakin
        return h
    if soal.tipe == "keputusan":
        h.lulus_otomatis = h.jenis_jawaban == "mesin_aturan"  # keputusan datang dari mesin aturan
        return h

    if h.fallback:
        h.catatan = "fallback (LLM/embedding tidak tersedia atau dokumen belum diingest)"
    urls = {_norm_url(s.get("url") or "") for s in h.sumber}
    if soal.sumber_url:
        h.sumber_cocok = _norm_url(soal.sumber_url) in urls
    if soal.halaman is not None:
        h.halaman_cocok = any(s.get("halaman") == soal.halaman for s in h.sumber)
    kunci = _angka(soal.jawaban_benar)
    if kunci:
        h.angka_cocok = kunci <= _angka(h.jawaban)
    h.lulus_otomatis = (
        h.yakin is True
        and h.sumber_cocok is not False
        and h.halaman_cocok is not False
        and h.angka_cocok is not False
    )
    return h


def jalankan_rag(client, soal: Sequence[SoalRag]) -> list[HasilRag]:
    """Satu sesi per pertanyaan (tanpa profil): cache LLM tetap berlaku, jatah sesi tidak terpakai."""
    hasil: list[HasilRag] = []
    for s in soal:
        with SesiEvaluasi(client) as sesi:
            try:
                header = sesi.buka()
                r = client.post(f"{API}/query", json={"pertanyaan": s.pertanyaan}, headers=header)
            except GoldenError as exc:
                hasil.append(nilai_satu(s, None, 0))
                hasil[-1].catatan = str(exc)
                continue
        hasil.append(nilai_satu(s, r.json() if r.status_code == 200 else None, r.status_code))
    return hasil


def ringkas_rag(hasil: Sequence[HasilRag]) -> dict[str, Any]:
    def rasio(daftar: list[HasilRag]) -> dict[str, Any]:
        n = len(daftar)
        lulus = sum(h.lulus_otomatis for h in daftar)
        return {"lulus": lulus, "total": n, "persen": round(100 * lulus / n, 1) if n else None}

    dalam = [h for h in hasil if h.soal.tipe == "dalam_cakupan"]
    luar = [h for h in hasil if h.soal.tipe == "di_luar_cakupan"]
    putusan = [h for h in hasil if h.soal.tipe == "keputusan"]
    return {
        "dalam_cakupan_proksi_otomatis": rasio(
            dalam
        ),  # sumber/halaman/angka; BUKAN akurasi jawaban
        "kejujuran_di_luar_cakupan": rasio(luar),  # yakin == false
        "keputusan_dari_mesin_aturan": rasio(putusan),
        "fallback": sum(bool(h.fallback) for h in hasil),
        "total": len(hasil),
    }


KOLOM_LAPORAN = [
    "no",
    "tipe",
    "pertanyaan",
    "jawaban_benar",
    "jawaban_sistem",
    "yakin",
    "jenis_jawaban",
    "fallback",
    "sumber_sistem",
    "sumber_cocok",
    "halaman_cocok",
    "angka_cocok",
    "lulus_otomatis",
    "catatan",
    "nilai_manual",  # diisi manusia: benar / sebagian / salah
]


def tulis_laporan_rag(hasil: Sequence[HasilRag], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=KOLOM_LAPORAN)
        w.writeheader()
        for h in hasil:
            w.writerow(
                {
                    "no": h.soal.nomor,
                    "tipe": h.soal.tipe,
                    "pertanyaan": h.soal.pertanyaan,
                    "jawaban_benar": h.soal.jawaban_benar,
                    "jawaban_sistem": h.jawaban,
                    "yakin": h.yakin,
                    "jenis_jawaban": h.jenis_jawaban,
                    "fallback": h.fallback,
                    "sumber_sistem": " | ".join(
                        f"{s.get('judul', '')} hal. {s.get('halaman')}: {s.get('url', '')}"
                        for s in h.sumber
                    ),
                    "sumber_cocok": h.sumber_cocok,
                    "halaman_cocok": h.halaman_cocok,
                    "angka_cocok": h.angka_cocok,
                    "lulus_otomatis": h.lulus_otomatis,
                    "catatan": h.catatan,
                    "nilai_manual": "",
                }
            )


def ringkas_gate(hasil: Sequence[Hasil]) -> dict[str, Any]:
    lulus = sum(h.ok for h in hasil)
    return {
        "lulus": lulus,
        "total": len(hasil),
        "persen": round(100 * lulus / len(hasil), 1) if hasil else None,
    }
