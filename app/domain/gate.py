"""Tahap 1: gate (syarat mutlak). Fungsi murni, tidak meng-import klien LLM (PRD 8.5).

Resolusi status per syarat -> status jalur (PRD 8.1):
  ada >= 1 `gagal`                         -> tidak_memenuhi_syarat (data_kurang diabaikan)
  tanpa `gagal`, ada >= 1 `data_kurang`    -> data_kurang (kembalikan pertanyaan, jangan menebak)
  semua `lolos` / `tidak_berlaku`          -> lolos
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.domain.expr import Konteks, bandingkan, evaluasi_nilai, parse_nilai
from app.domain.fields import FIELD_REGISTRY, Target, pertanyaan_untuk
from app.domain.ketentuan import Ketentuan, RuleError

StatusSyarat = Literal["lolos", "gagal", "data_kurang", "tidak_berlaku"]
StatusGate = Literal["lolos", "tidak_memenuhi_syarat", "data_kurang"]


@dataclass(frozen=True)
class Syarat:
    id: str
    field: str
    op: str
    nilai: str
    alasan_gagal: str
    sumber_url: str | None = None
    terakhir_diverifikasi: date | None = None


@dataclass(frozen=True)
class Rules:
    jalur: str
    tahun_siklus: int
    syarat: tuple[Syarat, ...]
    dokumen_wajib: tuple[Mapping[str, Any], ...] = ()
    sumber_url: str | None = None
    terakhir_diverifikasi: date | None = None


@dataclass(frozen=True)
class DataKurang:
    field: str
    pertanyaan: str


@dataclass(frozen=True)
class HasilSyarat:
    id: str
    status: StatusSyarat
    alasan: str | None = None
    data_kurang: tuple[DataKurang, ...] = ()


@dataclass(frozen=True)
class HasilGate:
    jalur: str
    status: StatusGate
    syarat: tuple[HasilSyarat, ...]
    data_kurang: tuple[DataKurang, ...] = field(default=())

    def ke_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "syarat": [
                {
                    "id": s.id,
                    "status": s.status,
                    "alasan": s.alasan,
                    "data_kurang": [d.field for d in s.data_kurang],
                }
                for s in self.syarat
            ],
        }


def _data_kurang(nama_field: str, target: Target | None) -> DataKurang:
    return DataKurang(nama_field, pertanyaan_untuk(nama_field, target))


def evaluasi_syarat(s: Syarat, k: Konteks) -> HasilSyarat | None:
    """None = syarat bersifat per-target tetapi target tidak diberikan (dilewati)."""
    fdef = FIELD_REGISTRY.get(s.field)
    if fdef is None:
        raise RuleError(f"Field '{s.field}' pada syarat {s.id} tidak terdaftar")
    if fdef.sumber == "target" and k.target is None:
        return None

    kiri = fdef.resolver(k.profil, k.target)
    if kiri.tidak_berlaku:
        return HasilSyarat(s.id, "tidak_berlaku", "Tidak berlaku untuk profilmu")

    if s.op == "exists":
        kurang = kiri.kurang
        kanan_nilai = None
    else:
        kanan = evaluasi_nilai(parse_nilai(s.nilai, s.op), k)
        kurang = tuple(dict.fromkeys(kiri.kurang + kanan.kurang))
        kanan_nilai = kanan.nilai

    if kurang:
        return HasilSyarat(
            s.id,
            "data_kurang",
            "Data belum lengkap untuk memeriksa syarat ini",
            tuple(_data_kurang(f, k.target) for f in kurang),
        )

    lolos = bandingkan(s.op, kiri.nilai, kanan_nilai)
    if lolos:
        return HasilSyarat(s.id, "lolos")
    return HasilSyarat(s.id, "gagal", s.alasan_gagal)


def evaluasi_gate(
    rules: Rules,
    profil: Mapping[str, Any],
    ketentuan: Ketentuan,
    target: Target | None = None,
) -> HasilGate:
    """Hasil sama untuk input yang sama; tidak bergantung pada LLM, jaringan, atau jam server."""
    k = Konteks(
        jalur=rules.jalur,
        tahun_siklus=rules.tahun_siklus,
        ketentuan=ketentuan,
        profil=profil,
        target=target,
    )
    hasil = tuple(h for s in rules.syarat if (h := evaluasi_syarat(s, k)) is not None)
    return HasilGate(
        jalur=rules.jalur,
        status=_status_jalur(hasil),
        syarat=hasil,
        data_kurang=_kumpulkan_data_kurang(hasil),
    )


def _status_jalur(hasil: Sequence[HasilSyarat]) -> StatusGate:
    status = {h.status for h in hasil}
    if "gagal" in status:
        return "tidak_memenuhi_syarat"
    if "data_kurang" in status:
        return "data_kurang"
    return "lolos"


def _kumpulkan_data_kurang(hasil: Sequence[HasilSyarat]) -> tuple[DataKurang, ...]:
    if any(h.status == "gagal" for h in hasil):
        return ()  # siswa yang sudah pasti gugur tidak diminta mengisi data tambahan
    unik: dict[str, DataKurang] = {}
    for h in hasil:
        for d in h.data_kurang:
            unik.setdefault(d.field, d)
    return tuple(unik.values())
