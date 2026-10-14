"""Analisis target (FR-T1 sampai T5): gate dulu, penilaian hanya bila gate lolos.

Orkestrasi di sini membaca DB lalu memanggil fungsi domain murni. Keputusan (lolos/gagal,
reach/match/safe) TIDAK pernah berasal dari LLM.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.errors import AppError
from app.db import models as m
from app.domain.assess_common import BasisPita, Keketatan, Penilaian, buat_basis_pita
from app.domain.assess_snbp import nilai_snbp
from app.domain.assess_snbt import AcuanSkor, nilai_snbt
from app.domain.fields import Target
from app.domain.gate import DataKurang, HasilGate, evaluasi_gate
from app.services.refdata import RefData

STATUS_TERVERIFIKASI = "terverifikasi"
STATUS_BELUM = "belum_diverifikasi"


@dataclass(frozen=True)
class SumberData:
    jenis: str  # rules_gate | keketatan | acuan_skor
    url: str | None
    terakhir_diverifikasi: date | None

    def ke_dict(self) -> dict[str, Any]:
        return {
            "jenis": self.jenis,
            "url": self.url,
            "terakhir_diverifikasi": self.terakhir_diverifikasi.isoformat()
            if self.terakhir_diverifikasi
            else None,
            "status_verifikasi": STATUS_TERVERIFIKASI
            if self.terakhir_diverifikasi
            else STATUS_BELUM,
        }


def ringkas_verifikasi(sumber: Sequence[SumberData]) -> tuple[date | None, str]:
    """Terverifikasi hanya bila SEMUA sumber yang dipakai punya tanggal verifikasi manusia."""
    if sumber and all(s.terakhir_diverifikasi for s in sumber):
        return min(
            s.terakhir_diverifikasi for s in sumber if s.terakhir_diverifikasi
        ), STATUS_TERVERIFIKASI
    return None, STATUS_BELUM


@dataclass(frozen=True)
class TargetDimuat:
    prodi: m.Prodi
    ptn: m.Ptn


def muat_target(db: Session, prodi_ids: Sequence[str]) -> dict[str, TargetDimuat]:
    """Muat prodi + PTN. Prodi yang tidak ada -> 404 dengan daftar lengkap."""
    unik = list(dict.fromkeys(prodi_ids))
    baris = db.execute(
        select(m.Prodi, m.Ptn).join(m.Ptn, m.Ptn.id == m.Prodi.ptn_id).where(m.Prodi.id.in_(unik))
    ).all()
    hasil = {p.id: TargetDimuat(p, t) for p, t in baris}
    hilang = [pid for pid in unik if pid not in hasil]
    if hilang:
        raise AppError(
            "prodi_tidak_ditemukan",
            "Ada prodi_id yang tidak ada di katalog",
            status_code=404,
            detail={"prodi_id": hilang},
        )
    return hasil


def _keketatan(
    db: Session, prodi_id: str, jalur: str, tahun_siklus: int
) -> tuple[Keketatan | None, m.ProdiJalur | None]:
    """Data keketatan terbaru yang tidak lebih baru dari siklus aktif."""
    baris = db.execute(
        select(m.ProdiJalur)
        .where(
            m.ProdiJalur.prodi_id == prodi_id,
            m.ProdiJalur.jalur == jalur,
            m.ProdiJalur.tahun_siklus <= tahun_siklus,
        )
        .order_by(m.ProdiJalur.tahun_siklus.desc())
        .limit(1)
    ).scalar_one_or_none()
    if baris is None:
        return None, None
    return Keketatan(baris.daya_tampung, baris.peminat, baris.tahun_peminat), baris


def _acuan(db: Session, prodi_id: str, jalur: str, tahun_siklus: int) -> m.AcuanSkor | None:
    return db.execute(
        select(m.AcuanSkor)
        .where(
            m.AcuanSkor.prodi_id == prodi_id,
            m.AcuanSkor.jalur == jalur,
            m.AcuanSkor.tahun <= tahun_siklus,
        )
        .order_by(m.AcuanSkor.tahun.desc())
        .limit(1)
    ).scalar_one_or_none()


def _basis_pita(ref: RefData, config: AppConfig, jalur: str, program: str) -> BasisPita:
    cfg = config.penilaian(jalur).pita_keketatan
    pembanding = ref.pembanding(jalur, program, cfg.kelompok)
    kelompok = f"program:{program}" if cfg.kelompok == "program" else "semua"
    return buat_basis_pita(cfg, pembanding, kelompok)


def _nilai(
    db: Session,
    ref: RefData,
    config: AppConfig,
    profil: Mapping[str, Any],
    t: TargetDimuat,
    jalur: str,
    sumber: list[SumberData],
) -> Penilaian | None:
    kek, baris_kek = _keketatan(db, t.prodi.id, jalur, ref.tahun_siklus)
    if baris_kek is not None:
        sumber.append(
            SumberData("keketatan", baris_kek.sumber_url, baris_kek.terakhir_diverifikasi)
        )
    cfg = config.penilaian(jalur)
    teks = config.teks.catatan_sel

    if jalur == "SNBT":
        baris_acuan = _acuan(db, t.prodi.id, jalur, ref.tahun_siklus)
        acuan = None
        if baris_acuan is not None:
            acuan = AcuanSkor(baris_acuan.rendah, baris_acuan.tinggi, baris_acuan.tahun)
            sumber.append(
                SumberData("acuan_skor", baris_acuan.sumber_url, baris_acuan.terakhir_diverifikasi)
            )
        hasil = nilai_snbt(
            profil,
            acuan=acuan,
            keketatan=kek,
            basis_pita=_basis_pita(ref, config, jalur, t.prodi.program),
            cfg=cfg,
            teks_catatan=teks,
            tahun_siklus=ref.tahun_siklus,
        )
    else:
        hasil = nilai_snbp(
            profil,
            prodi_id=t.prodi.id,
            ptn_id=t.ptn.id,
            keketatan=kek,
            basis_pita=_basis_pita(ref, config, jalur, t.prodi.program),
            cfg=cfg,
            teks_catatan=teks,
            tahun_siklus=ref.tahun_siklus,
        )
    if hasil.kategori == "belum_ada_acuan":
        # Tanpa data acuan tidak ada yang bisa diverifikasi: status hasil ini tidak boleh tampil
        # "terverifikasi" hanya karena syarat gate-nya terverifikasi. Sumber tanpa URL dan tanggal.
        sumber.append(SumberData("keketatan", None, None))
    return hasil


def analisis_satu(
    db: Session,
    ref: RefData,
    config: AppConfig,
    profil: Mapping[str, Any],
    t: TargetDimuat,
    jalur: str,
) -> dict[str, Any]:
    rules = ref.rules_untuk(jalur)
    gate: HasilGate = evaluasi_gate(rules, profil, ref.ketentuan, Target(t.prodi.id, t.prodi.nama))
    sumber: list[SumberData] = [
        SumberData("rules_gate", rules.sumber_url, rules.terakhir_diverifikasi)
    ]
    catatan: list[str] = []
    data_kurang: list[DataKurang] = list(gate.data_kurang)
    penilaian: Penilaian | None = None

    jalur_dibuka = t.prodi.jalur_dibuka
    if jalur_dibuka is not None and jalur not in jalur_dibuka:
        catatan.append(
            f"Data katalog belum mencatat {jalur} dibuka untuk prodi ini. Cek ulang di sumber resmi."
        )

    if gate.status == "lolos":
        penilaian = _nilai(db, ref, config, profil, t, jalur, sumber)
        if penilaian is not None:
            data_kurang.extend(penilaian.data_kurang)

    terakhir, status = ringkas_verifikasi(sumber)
    urls = list(dict.fromkeys(s.url for s in sumber if s.url))
    return {
        "prodi_id": t.prodi.id,
        "jalur": jalur,
        "prodi": {
            "nama": t.prodi.nama,
            "ptn_id": t.ptn.id,
            "ptn_nama": t.ptn.nama,
            "ptn_provinsi": t.ptn.provinsi,
            "jenjang": t.prodi.jenjang,
            "program": t.prodi.program,
        },
        "gate": gate.ke_dict(),
        "penilaian": penilaian.ke_dict() if penilaian else None,
        "sumber": urls,
        "sumber_detail": [s.ke_dict() for s in sumber],
        "terakhir_diverifikasi": terakhir.isoformat() if terakhir else None,
        "status_verifikasi": status,
        "data_kurang": [{"field": d.field, "pertanyaan": d.pertanyaan} for d in data_kurang],
        "catatan": catatan,
    }


def analisis_banyak(
    db: Session,
    ref: RefData,
    config: AppConfig,
    profil: Mapping[str, Any],
    targets: Sequence[tuple[str, Sequence[str]]],
) -> list[dict[str, Any]]:
    """`targets` = [(prodi_id, [jalur, ...])]. Urutan hasil mengikuti urutan permintaan."""
    dimuat = muat_target(db, [pid for pid, _ in targets])
    hasil: list[dict[str, Any]] = []
    terlihat: set[tuple[str, str]] = set()
    for prodi_id, daftar_jalur in targets:
        for jalur in daftar_jalur:
            if (prodi_id, jalur) in terlihat:
                continue
            terlihat.add((prodi_id, jalur))
            hasil.append(analisis_satu(db, ref, config, profil, dimuat[prodi_id], jalur))
    return hasil
