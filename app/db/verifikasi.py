"""Pemeriksaan data yang belum diverifikasi manusia (`terakhir_diverifikasi` kosong).

`terakhir_diverifikasi` hanya diisi manusia, tidak pernah otomatis. Dengan REQUIRE_VERIFIED=true,
aplikasi menolak start bila tabel kritis (aturan yang memutuskan lolos/tidak dan kategori) masih
memuat baris tanpa tanggal. Tabel kosong dianggap lolos agar urutan deploy "naikkan stack, lalu
ingest" tetap mungkin; ingest sendiri menolak baris tanpa tanggal bila REQUIRE_VERIFIED aktif.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import ConfigError
from app.db import models as m

TABEL_KRITIS = ("rules_jalur", "ketentuan", "acuan_skor")
TABEL_KATALOG = ("ptn", "prodi", "prodi_jalur", "dokumen_sumber")


@dataclass(frozen=True)
class TemuanVerifikasi:
    tabel: str
    kunci: str
    alasan: str


def _rules(db: Session) -> list[TemuanVerifikasi]:
    hasil: list[TemuanVerifikasi] = []
    for r in db.scalars(select(m.RulesJalur).order_by(m.RulesJalur.id)):
        syarat = [s["id"] for s in r.syarat if not s.get("terakhir_diverifikasi")]
        dokumen = [d["nama"] for d in r.dokumen_wajib if not d.get("terakhir_diverifikasi")]
        if r.terakhir_diverifikasi is None or syarat or dokumen:
            bagian = []
            if syarat:
                bagian.append(f"{len(syarat)} dari {len(r.syarat)} syarat")
            if dokumen:
                bagian.append(f"{len(dokumen)} dari {len(r.dokumen_wajib)} dokumen wajib")
            hasil.append(
                TemuanVerifikasi(
                    "rules_jalur",
                    r.id,
                    "tanpa tanggal verifikasi: " + (", ".join(bagian) or "baris rule"),
                )
            )
    return hasil


def _baris(db: Session, tabel: str, model, kunci) -> list[TemuanVerifikasi]:
    return [
        TemuanVerifikasi(tabel, kunci(b), "terakhir_diverifikasi kosong")
        for b in db.scalars(select(model).where(model.terakhir_diverifikasi.is_(None)))
    ]


def cari_belum_terverifikasi(db: Session, *, lengkap: bool = False) -> list[TemuanVerifikasi]:
    """Baris tanpa tanggal verifikasi. `lengkap=True` menyertakan katalog (ptn, prodi, dst)."""
    hasil = _rules(db)
    hasil += _baris(db, "ketentuan", m.Ketentuan, lambda b: f"{b.key}|{b.jalur}|{b.tahun_siklus}")
    hasil += _baris(
        db,
        "acuan_skor",
        m.AcuanSkor,
        lambda b: f"{b.prodi_id}|{b.jalur}|{b.tahun}",
    )
    if lengkap:
        hasil += _baris(db, "ptn", m.Ptn, lambda b: b.id)
        hasil += _baris(db, "prodi", m.Prodi, lambda b: b.id)
        hasil += _baris(
            db,
            "prodi_jalur",
            m.ProdiJalur,
            lambda b: f"{b.prodi_id}|{b.jalur}|{b.tahun_siklus}",
        )
        hasil += _baris(db, "dokumen_sumber", m.DokumenSumber, lambda b: b.id)
    return hasil


_MODEL = {
    "rules_jalur": m.RulesJalur,
    "ketentuan": m.Ketentuan,
    "acuan_skor": m.AcuanSkor,
    "ptn": m.Ptn,
    "prodi": m.Prodi,
    "prodi_jalur": m.ProdiJalur,
    "dokumen_sumber": m.DokumenSumber,
}


def hitung_per_tabel(db: Session, *, lengkap: bool = False) -> dict[str, tuple[int, int]]:
    """{tabel: (belum_terverifikasi, total_baris)} untuk tabel kritis (dan katalog bila lengkap)."""
    tabel = TABEL_KRITIS + (TABEL_KATALOG if lengkap else ())
    belum = ringkas_per_tabel(cari_belum_terverifikasi(db, lengkap=lengkap))
    return {
        t: (belum.get(t, 0), db.scalar(select(func.count()).select_from(_MODEL[t])) or 0)
        for t in tabel
    }


def ringkas_per_tabel(temuan: list[TemuanVerifikasi]) -> dict[str, int]:
    hasil: dict[str, int] = {}
    for t in temuan:
        hasil[t.tabel] = hasil.get(t.tabel, 0) + 1
    return hasil


def pastikan_terverifikasi(db: Session) -> None:
    """Guard startup (REQUIRE_VERIFIED=true). ConfigError bila tabel kritis berisi data belum terverifikasi."""
    temuan = cari_belum_terverifikasi(db)
    if not temuan:
        return
    per_tabel = ", ".join(f"{t}: {n}" for t, n in ringkas_per_tabel(temuan).items())
    contoh = "; ".join(f"{t.tabel}/{t.kunci}" for t in temuan[:3])
    raise ConfigError(
        f"REQUIRE_VERIFIED=true, tetapi ada data kritis yang belum diverifikasi ({per_tabel}). "
        f"Contoh: {contoh}. Isi terakhir_diverifikasi setelah verifikasi manusia lalu ingest ulang, "
        "atau matikan REQUIRE_VERIFIED. Daftar lengkap: python -m scripts.check_verified"
    )
