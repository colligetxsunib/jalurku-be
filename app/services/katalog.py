"""Katalog PTN dan prodi (FR-C1, FR-C2): daftar berpaginasi, filter, dan detail.

Tidak ada nilai tebakan: prodi tanpa data acuan mengembalikan `acuan: null` dan
`status_acuan: "belum_ada_acuan"`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m

STATUS_TERVERIFIKASI = "terverifikasi"
STATUS_BELUM = "belum_diverifikasi"


def status_verifikasi(tanggal: date | None) -> str:
    return STATUS_TERVERIFIKASI if tanggal else STATUS_BELUM


def _iso(tanggal: date | None) -> str | None:
    return tanggal.isoformat() if tanggal else None


def _like(teks: str) -> str:
    """Pola ILIKE aman: karakter % _ \\ dari pengguna diperlakukan sebagai teks biasa."""
    escaped = teks.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(frozen=True)
class Halaman:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def _bungkus(items: list[dict[str, Any]], total: int, h: Halaman) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": h.page,
        "limit": h.limit,
        "total_halaman": ceil(total / h.limit) if total else 0,
    }


def _hitung(db: Session, kueri: Select) -> int:
    return db.execute(
        select(func.count()).select_from(kueri.order_by(None).subquery())
    ).scalar_one()


# ----------------------------------------------------------------------------- PTN


def daftar_ptn(db: Session, *, q: str | None, provinsi: str | None, h: Halaman) -> dict[str, Any]:
    jumlah_prodi = (
        select(func.count(m.Prodi.id))
        .where(m.Prodi.ptn_id == m.Ptn.id)
        .correlate(m.Ptn)
        .scalar_subquery()
    )
    kueri = select(m.Ptn.id, m.Ptn.nama, m.Ptn.provinsi, jumlah_prodi.label("jumlah_prodi"))
    if q:
        kueri = kueri.where(m.Ptn.nama.ilike(_like(q), escape="\\"))
    if provinsi:
        kueri = kueri.where(m.Ptn.provinsi == provinsi)
    total = _hitung(db, kueri)
    baris = db.execute(kueri.order_by(m.Ptn.nama, m.Ptn.id).offset(h.offset).limit(h.limit)).all()
    items = [{"id": i, "nama": n, "provinsi": p, "jumlah_prodi": jp} for i, n, p, jp in baris]
    return _bungkus(items, total, h)


# ----------------------------------------------------------------------------- prodi


def daftar_prodi(
    db: Session,
    *,
    q: str | None,
    rumpun: str | None,
    provinsi: str | None,
    jalur: str | None,
    ptn_id: str | None,
    program: str | None,
    jenjang: str | None,
    h: Halaman,
) -> dict[str, Any]:
    ada_keketatan = exists().where(m.ProdiJalur.prodi_id == m.Prodi.id)
    kueri = select(m.Prodi, m.Ptn, ada_keketatan.label("ada_keketatan")).join(
        m.Ptn, m.Ptn.id == m.Prodi.ptn_id
    )
    if q:
        kueri = kueri.where(m.Prodi.nama.ilike(_like(q), escape="\\"))
    if rumpun:
        kueri = kueri.where(func.lower(m.Prodi.rumpun) == rumpun.casefold())
    if provinsi:
        kueri = kueri.where(m.Ptn.provinsi == provinsi)
    if jalur:  # hanya prodi yang katalognya MENCATAT jalur itu dibuka (NULL = belum diketahui)
        kueri = kueri.where(m.Prodi.jalur_dibuka.contains([jalur]))
    if ptn_id:
        kueri = kueri.where(m.Prodi.ptn_id == ptn_id)
    if program:
        kueri = kueri.where(m.Prodi.program == program)
    if jenjang:
        kueri = kueri.where(m.Prodi.jenjang == jenjang)

    total = _hitung(db, kueri)
    baris = db.execute(
        kueri.order_by(m.Prodi.nama, m.Ptn.nama, m.Prodi.id).offset(h.offset).limit(h.limit)
    ).all()
    items = [
        {
            "id": p.id,
            "nama": p.nama,
            "ptn": {"id": t.id, "nama": t.nama, "provinsi": t.provinsi},
            "rumpun": p.rumpun,
            "jenjang": p.jenjang,
            "program": p.program,
            "akreditasi": p.akreditasi,
            "jalur_dibuka": p.jalur_dibuka,
            "punya_data_keketatan": bool(ada),
            "status_verifikasi": status_verifikasi(p.terakhir_diverifikasi),
        }
        for p, t, ada in baris
    ]
    return _bungkus(items, total, h)


def detail_prodi(db: Session, prodi_id: str) -> dict[str, Any]:
    baris = db.execute(
        select(m.Prodi, m.Ptn).join(m.Ptn, m.Ptn.id == m.Prodi.ptn_id).where(m.Prodi.id == prodi_id)
    ).one_or_none()
    if baris is None:
        raise AppError(
            "prodi_tidak_ditemukan",
            f"Prodi '{prodi_id}' tidak ada di katalog",
            status_code=404,
            detail={"prodi_id": [prodi_id]},
        )
    p, t = baris

    keketatan: dict[str, Any] = {}
    for k in db.execute(
        select(m.ProdiJalur)
        .where(m.ProdiJalur.prodi_id == prodi_id)
        .order_by(m.ProdiJalur.jalur, m.ProdiJalur.tahun_siklus.desc())
    ).scalars():
        if k.jalur in keketatan:  # hanya siklus terbaru per jalur
            continue
        rasio = k.peminat / k.daya_tampung if k.daya_tampung and k.peminat is not None else None
        keketatan[k.jalur] = {
            "daya_tampung": k.daya_tampung,
            "peminat": k.peminat,
            "tahun_peminat": k.tahun_peminat,
            "tahun_siklus": k.tahun_siklus,
            "rasio_peminat_per_kursi": round(rasio, 2) if rasio is not None else None,
            "sumber_url": k.sumber_url,
            "terakhir_diverifikasi": _iso(k.terakhir_diverifikasi),
            "status_verifikasi": status_verifikasi(k.terakhir_diverifikasi),
        }

    acuan: dict[str, Any] = {}
    for a in db.execute(
        select(m.AcuanSkor)
        .where(m.AcuanSkor.prodi_id == prodi_id)
        .order_by(m.AcuanSkor.jalur, m.AcuanSkor.tahun.desc())
    ).scalars():
        if a.jalur in acuan:
            continue
        acuan[a.jalur] = {
            "rendah": a.rendah,
            "tinggi": a.tinggi,
            "tahun": a.tahun,
            "label": "acuan siklus sebelumnya",
            "sumber_url": a.sumber_url,
            "terakhir_diverifikasi": _iso(a.terakhir_diverifikasi),
            "status_verifikasi": status_verifikasi(a.terakhir_diverifikasi),
        }

    return {
        "id": p.id,
        "nama": p.nama,
        "ptn": {"id": t.id, "nama": t.nama, "provinsi": t.provinsi},
        "rumpun": p.rumpun,
        "jenjang": p.jenjang,
        "program": p.program,
        "akreditasi": p.akreditasi,
        "mapel_penentu": p.mapel_penentu,
        "tag_minat": p.tag_minat,
        "jalur_dibuka": p.jalur_dibuka,
        "keketatan": keketatan,
        "status_keketatan": "ada" if keketatan else "belum_ada_data",
        "acuan": acuan or None,
        "status_acuan": "ada" if acuan else "belum_ada_acuan",
        "sumber_url": p.sumber_url,
        "terakhir_diverifikasi": _iso(p.terakhir_diverifikasi),
        "status_verifikasi": status_verifikasi(p.terakhir_diverifikasi),
    }
