"""Layanan ingest: satu batch = satu transaksi (semua berhasil atau tidak sama sekali), idempoten.

Dipakai bersama oleh `POST /admin/ingest` dan CLI `scripts/ingest.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import models as m
from app.ingest.acuan import acuan_dari_baris
from app.ingest.csv_io import baca_csv
from app.ingest.dokumen import dokumen_dari_baris
from app.ingest.katalog import katalog_dari_baris
from app.ingest.ketentuan import ketentuan_dari_baris
from app.ingest.profesi import profesi_dari_baris
from app.ingest.rules import dokumen_wajib_dari_baris, rules_dari_baris
from app.ingest.umum import ErrorBaris, Kebijakan
from app.services.refdata import tahun_acuan

TIPE_VALID = ("rules", "ketentuan", "katalog", "acuan", "dokumen", "profesi")
URUTAN_SEED = (
    "ketentuan",
    "rules",
    "katalog",
    "acuan",
    "dokumen",
    "profesi",
)  # profesi setelah katalog
_CHUNK = 500


@dataclass
class HasilIngest:
    tipe: str
    diterima: int = 0
    error: list[ErrorBaris] = field(default_factory=list)
    ringkasan: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    def ke_dict(self) -> dict[str, Any]:
        return {
            "tipe": self.tipe,
            "diterima": self.diterima,
            "ringkasan": self.ringkasan,
            "error": [e.ke_dict() for e in self.error],
        }


def _upsert(
    db: Session,
    model: type,
    baris: Sequence[Mapping[str, Any]],
    kunci: Sequence[str],
    perbarui: Sequence[str] | None = None,
) -> None:
    if not baris:
        return
    kolom_update = (
        list(perbarui)
        if perbarui is not None
        else [
            c.name
            for c in model.__table__.columns
            if c.name not in kunci  # type: ignore[attr-defined]
        ]
    )
    for i in range(0, len(baris), _CHUNK):
        stmt = pg_insert(model).values([dict(b) for b in baris[i : i + _CHUNK]])
        stmt = stmt.on_conflict_do_update(
            index_elements=list(kunci), set_={c: stmt.excluded[c] for c in kolom_update}
        )
        db.execute(stmt)


# ------------------------------- handler per tipe -------------------------------


def _ingest_ketentuan(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    item, galat = ketentuan_dari_baris(payload, k)
    hasil = HasilIngest("ketentuan", error=galat)
    if galat:
        return hasil
    _upsert(db, m.Ketentuan, item, ("key", "jalur", "tahun_siklus"))
    hasil.diterima = len(item)
    hasil.ringkasan = {"ketentuan": len(item)}
    return hasil


def _ingest_rules(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    baris_syarat = [p for p in payload if "nama_dokumen" not in p]
    baris_dok = [p for p in payload if "nama_dokumen" in p]
    daftar_rules, galat = rules_dari_baris(baris_syarat, kebijakan=k)
    dok, galat_dok = dokumen_wajib_dari_baris(baris_dok, kebijakan=k)
    galat = galat + galat_dok

    ada_di_batch = {(r.jalur, r.tahun_siklus) for r in daftar_rules}
    tahun_per_jalur: dict[str, int] = {}
    for jalur, tahun in ada_di_batch:
        tahun_per_jalur[jalur] = max(tahun, tahun_per_jalur.get(jalur, 0))

    def tahun_dokumen(jalur: str, tahun: int | None, no: int) -> int | None:
        if tahun is not None:
            return tahun
        if jalur in tahun_per_jalur:
            return tahun_per_jalur[jalur]
        ada = db.execute(
            select(func.max(m.RulesJalur.tahun_siklus)).where(m.RulesJalur.jalur == jalur)
        ).scalar()
        if ada is None:
            galat.append(
                ErrorBaris(
                    "dokumen_wajib",
                    no,
                    f"belum ada rules {jalur}; ingest syarat dulu atau isi tahun_siklus",
                )
            )
        return ada

    dok_per_kunci: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for no, jalur, tahun, item in dok:
        t = tahun_dokumen(jalur, tahun, no)
        if t is not None:
            dok_per_kunci.setdefault((jalur, t), []).append(item)

    # dokumen untuk kombinasi yang tidak ada di batch syarat harus merujuk rules yang sudah ada
    hanya_dok = [kunci for kunci in dok_per_kunci if kunci not in ada_di_batch]
    for jalur, tahun in hanya_dok:
        if db.get(m.RulesJalur, f"{jalur}-{tahun}") is None:
            galat.append(ErrorBaris("dokumen_wajib", 0, f"rules {jalur} {tahun} belum ada"))
    if galat:
        return HasilIngest("rules", error=galat)

    dengan_dok, tanpa_dok = [], []
    for r in daftar_rules:
        baris = {
            "id": f"{r.jalur}-{r.tahun_siklus}",
            "jalur": r.jalur,
            "tahun_siklus": r.tahun_siklus,
            "syarat": [
                {
                    "id": s.id,
                    "field": s.field,
                    "op": s.op,
                    "nilai": s.nilai,
                    "alasan_gagal": s.alasan_gagal,
                    "sumber_url": s.sumber_url,
                    "terakhir_diverifikasi": s.terakhir_diverifikasi.isoformat()
                    if s.terakhir_diverifikasi
                    else None,
                }
                for s in r.syarat
            ],
            "sumber_url": r.sumber_url,
            "terakhir_diverifikasi": r.terakhir_diverifikasi,
        }
        if (r.jalur, r.tahun_siklus) in dok_per_kunci:
            dengan_dok.append({**baris, "dokumen_wajib": dok_per_kunci[(r.jalur, r.tahun_siklus)]})
        else:
            tanpa_dok.append(baris)  # dokumen_wajib lama dipertahankan
    kunci = ("id",)
    semua_kolom = ["jalur", "tahun_siklus", "syarat", "sumber_url", "terakhir_diverifikasi"]
    _upsert(db, m.RulesJalur, dengan_dok, kunci, semua_kolom + ["dokumen_wajib"])
    _upsert(db, m.RulesJalur, tanpa_dok, kunci, semua_kolom)
    for jalur, tahun in hanya_dok:
        db.execute(
            update(m.RulesJalur)
            .where(m.RulesJalur.id == f"{jalur}-{tahun}")
            .values(dokumen_wajib=dok_per_kunci[(jalur, tahun)])
        )

    n_syarat = sum(len(r.syarat) for r in daftar_rules)
    n_dok = sum(len(v) for v in dok_per_kunci.values())
    return HasilIngest(
        "rules",
        diterima=n_syarat + n_dok,
        ringkasan={"rules_jalur": len(daftar_rules), "syarat": n_syarat, "dokumen_wajib": n_dok},
    )


def _ingest_katalog(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    kat = katalog_dari_baris(payload, k, tahun_default=tahun_acuan(db))
    galat = list(kat.error)
    ptn_ada = set(db.execute(select(m.Ptn.id)).scalars()) | {p["id"] for p in kat.ptn}
    for p in kat.prodi:
        if p["ptn_id"] not in ptn_ada and p["ptn_id"] not in kat.ptn_ditolak:
            galat.append(
                ErrorBaris(
                    "katalog",
                    kat.baris_prodi[p["id"]],
                    f"ptn_id '{p['ptn_id']}' tidak ada di katalog PTN",
                )
            )
    if galat:
        return HasilIngest("katalog", error=sorted(galat, key=lambda e: e.baris))
    _upsert(db, m.Ptn, kat.ptn, ("id",))
    _upsert(db, m.Prodi, kat.prodi, ("id",))
    _upsert(db, m.ProdiJalur, kat.prodi_jalur, ("prodi_id", "jalur", "tahun_siklus"))
    return HasilIngest(
        "katalog",
        diterima=len(kat.ptn) + len(kat.prodi),
        ringkasan={
            "ptn": len(kat.ptn),
            "prodi": len(kat.prodi),
            "prodi_jalur": len(kat.prodi_jalur),
        },
    )


def _ingest_acuan(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    item, galat = acuan_dari_baris(payload, k)
    prodi_ada = set(db.execute(select(m.Prodi.id)).scalars())
    for a in item:
        if a["prodi_id"] not in prodi_ada:
            galat.append(
                ErrorBaris(
                    "acuan_skor", a["_baris"], f"prodi_id '{a['prodi_id']}' tidak ada di katalog"
                )
            )
    if galat:
        return HasilIngest("acuan", error=sorted(galat, key=lambda e: e.baris))
    bersih = [{kk: v for kk, v in a.items() if kk != "_baris"} for a in item]
    _upsert(db, m.AcuanSkor, bersih, ("prodi_id", "jalur", "tahun"))
    return HasilIngest("acuan", diterima=len(bersih), ringkasan={"acuan_skor": len(bersih)})


def _ingest_dokumen(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    item, galat = dokumen_dari_baris(payload, k)
    if galat:
        return HasilIngest("dokumen", error=galat)
    _upsert(db, m.DokumenSumber, item, ("id",))
    return HasilIngest("dokumen", diterima=len(item), ringkasan={"dokumen_sumber": len(item)})


def _ingest_profesi(db: Session, payload: list[Mapping[str, Any]], k: Kebijakan) -> HasilIngest:
    item, galat = profesi_dari_baris(payload)
    rumpun_ada = set(db.execute(select(m.Prodi.rumpun).distinct()).scalars())
    for p in item:
        if p["rumpun"] not in rumpun_ada:
            galat.append(
                ErrorBaris(
                    "profesi",
                    0,
                    f"rumpun '{p['rumpun']}' (id {p['id']}) tidak ada di katalog prodi; "
                    "ingest katalog dulu atau samakan penulisan rumpun",
                )
            )
    if galat:
        return HasilIngest("profesi", error=galat)
    _upsert(db, m.Profesi, item, ("id",))
    return HasilIngest("profesi", diterima=len(item), ringkasan={"profesi": len(item)})


_HANDLER: dict[str, Callable[[Session, list[Mapping[str, Any]], Kebijakan], HasilIngest]] = {
    "ketentuan": _ingest_ketentuan,
    "rules": _ingest_rules,
    "katalog": _ingest_katalog,
    "acuan": _ingest_acuan,
    "dokumen": _ingest_dokumen,
    "profesi": _ingest_profesi,
}


def ingest(
    db: Session,
    tipe: str,
    payload: Sequence[Mapping[str, Any]],
    *,
    require_verified: bool = False,
    hari_ini: date | None = None,
) -> HasilIngest:
    """Jalankan satu batch dalam satu transaksi. Ada error satu baris pun = tidak ada yang tersimpan."""
    if tipe not in _HANDLER:
        raise ValueError(f"tipe harus salah satu dari {TIPE_VALID}")
    kebijakan = Kebijakan(require_verified=require_verified, hari_ini=hari_ini or date.today())
    try:
        hasil = _HANDLER[tipe](db, list(payload), kebijakan)
        if hasil.error:
            db.rollback()
            hasil.diterima = 0
            hasil.ringkasan = {}
            return hasil
        db.commit()
        return hasil
    except Exception:
        db.rollback()
        raise


# ------------------------------- seed dari direktori CSV -------------------------------

_BERKAS: dict[str, list[tuple[str, bool]]] = {  # (nama berkas, wajib)
    "ketentuan": [("config_ketentuan.csv", True)],
    "rules": [("rule_gate.csv", True), ("dokumen_wajib.csv", False)],
    "katalog": [("ptn.csv", True), ("prodi.csv", True)],
    "acuan": [("acuan_skor_snbt.csv", False)],
    "dokumen": [("dokumen_rag_metadata.csv", False)],
    "profesi": [("profesi.csv", False)],
}


def baca_payload_seed(
    direktori: str | Path, tipe: str
) -> tuple[list[dict[str, str]], list[ErrorBaris]]:
    payload: list[dict[str, str]] = []
    galat: list[ErrorBaris] = []
    for nama, wajib in _BERKAS[tipe]:
        path = Path(direktori) / nama
        if not path.is_file():
            if wajib:
                galat.append(ErrorBaris(nama, 0, f"berkas tidak ditemukan: {path}"))
            continue
        payload.extend(baca_csv(path))
    return payload, galat


def ingest_direktori(
    db: Session,
    direktori: str | Path,
    *,
    require_verified: bool = False,
    tipe: Sequence[str] | None = None,
) -> list[HasilIngest]:
    """Ingest seluruh CSV seed berurutan (ketentuan, rules, katalog, acuan, dokumen)."""
    hasil: list[HasilIngest] = []
    for t in URUTAN_SEED:
        if tipe is not None and t not in tipe:
            continue
        payload, galat = baca_payload_seed(direktori, t)
        if galat:
            hasil.append(HasilIngest(t, error=galat))
            continue
        hasil.append(ingest(db, t, payload, require_verified=require_verified))
    return hasil
