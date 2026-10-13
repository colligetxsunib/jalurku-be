"""Data referensi (rules gate + ketentuan resmi) dimuat dari DB menjadi objek domain, di-cache.

Cache dibuang (`invalidate`) setiap kali ingest berhasil.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models as m
from app.domain.gate import Rules, Syarat
from app.domain.ketentuan import Ketentuan


@dataclass(frozen=True)
class RasioProdi:
    prodi_id: str
    program: str  # akademik | vokasi
    rasio: float  # peminat / daya tampung


@dataclass(frozen=True)
class RefData:
    tahun_siklus: int
    ketentuan: Ketentuan
    rules: dict[str, Rules]  # kunci = jalur ("SNBP" / "SNBT"), untuk tahun_siklus aktif
    # Prodi pembanding untuk pita keketatan: jalur -> rasio peminat/daya tampung (tahun_siklus aktif)
    rasio: dict[str, tuple[RasioProdi, ...]] = field(default_factory=dict)

    def pembanding(self, jalur: str, program: str, kelompok: str) -> list[float]:
        """Rasio prodi pembanding. kelompok='program' membatasi pada program yang sama."""
        semua = self.rasio.get(jalur, ())
        return [r.rasio for r in semua if kelompok != "program" or r.program == program]

    def rules_untuk(self, jalur: str) -> Rules:
        if jalur not in self.rules:
            raise AppError(
                "rules_belum_dimuat",
                f"Rule gate {jalur} untuk siklus {self.tahun_siklus} belum dimuat",
                status_code=503,
            )
        return self.rules[jalur]


def tahun_acuan(db: Session) -> int | None:
    """Tahun siklus aktif = nilai terbesar `tahun_acuan_pendaftaran` di tabel ketentuan."""
    nilai = db.execute(
        select(m.Ketentuan.nilai).where(m.Ketentuan.key == "tahun_acuan_pendaftaran")
    ).scalars()
    tahun = [int(float(n)) for n in nilai if n.strip().replace(".", "", 1).isdigit()]
    return max(tahun) if tahun else None


def _tanggal(teks: str | None) -> date | None:
    return date.fromisoformat(teks) if teks else None


def _ke_rules(baris: m.RulesJalur) -> Rules:
    return Rules(
        jalur=baris.jalur,
        tahun_siklus=baris.tahun_siklus,
        syarat=tuple(
            Syarat(
                id=s["id"],
                field=s["field"],
                op=s["op"],
                nilai=s["nilai"],
                alasan_gagal=s["alasan_gagal"],
                sumber_url=s.get("sumber_url"),
                terakhir_diverifikasi=_tanggal(s.get("terakhir_diverifikasi")),
            )
            for s in baris.syarat
        ),
        dokumen_wajib=tuple(baris.dokumen_wajib or ()),
        sumber_url=baris.sumber_url,
        terakhir_diverifikasi=baris.terakhir_diverifikasi,
    )


def muat_refdata(db: Session) -> RefData:
    tahun = tahun_acuan(db)
    if tahun is None:
        raise AppError(
            "ketentuan_belum_dimuat",
            "Ketentuan resmi (tahun_acuan_pendaftaran) belum dimuat. Jalankan ingest data.",
            status_code=503,
        )
    baris: list[dict[str, Any]] = [
        {
            "key": k.key,
            "jalur": k.jalur,
            "tahun_siklus": k.tahun_siklus,
            "nilai": k.nilai,
            "nilai_terstruktur": k.nilai_terstruktur,
        }
        for k in db.execute(select(m.Ketentuan)).scalars()
    ]
    rules = {
        r.jalur: _ke_rules(r)
        for r in db.execute(
            select(m.RulesJalur).where(m.RulesJalur.tahun_siklus == tahun)
        ).scalars()
    }
    rasio: dict[str, list[RasioProdi]] = {}
    kueri = (
        select(
            m.ProdiJalur.jalur,
            m.ProdiJalur.prodi_id,
            m.Prodi.program,
            m.ProdiJalur.daya_tampung,
            m.ProdiJalur.peminat,
        )
        .join(m.Prodi, m.Prodi.id == m.ProdiJalur.prodi_id)
        .where(
            m.ProdiJalur.tahun_siklus == tahun,
            m.ProdiJalur.daya_tampung > 0,
            m.ProdiJalur.peminat.is_not(None),
        )
        .order_by(m.ProdiJalur.jalur, m.ProdiJalur.prodi_id)
    )
    for jalur, prodi_id, program, daya, peminat in db.execute(kueri):
        rasio.setdefault(jalur, []).append(RasioProdi(prodi_id, program, peminat / daya))
    return RefData(
        tahun_siklus=tahun,
        ketentuan=Ketentuan.dari_baris(baris),
        rules=rules,
        rasio={j: tuple(v) for j, v in rasio.items()},
    )


class RefDataProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: RefData | None = None

    def get(self, db: Session) -> RefData:
        with self._lock:
            if self._data is None:
                self._data = muat_refdata(db)
            return self._data

    def invalidate(self) -> None:
        with self._lock:
            self._data = None
