"""Evaluator rule gate: operator whitelist dan ekspresi terbatas. TANPA eval().

Ekspresi nilai yang didukung (sisi kanan rule):
  true / false            boolean
  25, 3.5                 angka
  tahun_siklus[+-N]       tahun siklus pendaftaran, mis. tahun_siklus-2
  SMA|SMK|MA              daftar (untuk operator `in`)
  config:fn(arg1,arg2)    fungsi terdaftar yang membaca ketentuan; argumen = field profil
  teks lain               string literal
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.fields import (
    AKREDITASI,
    ARGUMEN_PROFIL,
    FIELD_REGISTRY,
    Resolved,
    Target,
)
from app.domain.ketentuan import Ketentuan, RuleError

OPERATOR = frozenset({"==", "!=", "<=", ">=", "<", ">", "in", "exists"})
_URUTAN = frozenset({"<=", ">=", "<", ">"})

_RE_TAHUN = re.compile(r"^tahun_siklus\s*(?:([+-])\s*(\d+))?$")
_RE_FUNGSI = re.compile(r"^config:([A-Za-z_]\w*)\((.*)\)$")
_RE_INT = re.compile(r"^-?\d+$")
_RE_FLOAT = re.compile(r"^-?\d+\.\d+$")
_RE_IDENT = re.compile(r"^[A-Za-z_]\w*$")


@dataclass(frozen=True)
class Literal:
    nilai: Any


@dataclass(frozen=True)
class TahunSiklus:
    offset: int


@dataclass(frozen=True)
class Daftar:
    item: tuple[str, ...]


@dataclass(frozen=True)
class PanggilanConfig:
    nama: str
    argumen: tuple[str, ...]


NilaiExpr = Literal | TahunSiklus | Daftar | PanggilanConfig


@dataclass(frozen=True)
class Konteks:
    jalur: str
    tahun_siklus: int
    ketentuan: Ketentuan
    profil: Mapping[str, Any]
    target: Target | None = None


@dataclass(frozen=True)
class FungsiDef:
    argumen: tuple[str, ...]
    hitung: Callable[..., float]


def _kuota_sekolah_persen(
    ketentuan: Ketentuan, jalur: str, tahun: int, akreditasi: str, pakai_erapor: bool
) -> float:
    if akreditasi not in AKREDITASI:
        raise RuleError(f"Akreditasi tidak dikenal: {akreditasi!r}")
    kode = akreditasi if akreditasi in ("A", "B") else "C_dan_lainnya"
    dasar = ketentuan.angka(f"kuota_sekolah_persen_akreditasi_{kode}", jalur, tahun)
    bonus = (
        ketentuan.angka("kuota_sekolah_bonus_erapor_persen", jalur, tahun) if pakai_erapor else 0.0
    )
    return dasar + bonus


FUNGSI_CONFIG: dict[str, FungsiDef] = {
    "kuota_sekolah_persen": FungsiDef(
        ("akreditasi_sekolah", "pakai_erapor"), _kuota_sekolah_persen
    ),
}


def parse_nilai(raw: str, op: str = "==") -> NilaiExpr:
    teks = raw.strip()
    if (m := _RE_FUNGSI.match(teks)) is not None:
        nama = m.group(1)
        argumen = tuple(a.strip() for a in m.group(2).split(",") if a.strip())
        if nama not in FUNGSI_CONFIG:
            raise RuleError(f"Fungsi config tidak dikenal: {nama}")
        return PanggilanConfig(nama, argumen)
    if (m := _RE_TAHUN.match(teks)) is not None:
        if m.group(1) is None:
            return TahunSiklus(0)
        selisih = int(m.group(2))
        return TahunSiklus(selisih if m.group(1) == "+" else -selisih)
    if "|" in teks:
        return Daftar(tuple(x.strip() for x in teks.split("|") if x.strip()))
    if teks.lower() in ("true", "false"):
        return Literal(teks.lower() == "true")
    if _RE_INT.match(teks):
        return Literal(int(teks))
    if _RE_FLOAT.match(teks):
        return Literal(float(teks))
    if op == "in":
        return Daftar((teks,))
    return Literal(teks)


def validasi_syarat(field: str, op: str, raw_nilai: str) -> list[str]:
    """Pemeriksaan statis saat ingest. Kembalikan daftar pesan error (kosong = valid)."""
    galat: list[str] = []
    if op not in OPERATOR:
        galat.append(f"operator '{op}' tidak diizinkan (whitelist: {', '.join(sorted(OPERATOR))})")
    fdef = FIELD_REGISTRY.get(field)
    if fdef is None:
        galat.append(f"field '{field}' tidak terdaftar di registry field")
    if galat:
        return galat
    if op == "exists":
        return galat
    try:
        expr = parse_nilai(raw_nilai, op)
    except RuleError as exc:
        return [str(exc)]
    if isinstance(expr, PanggilanConfig):
        fungsi = FUNGSI_CONFIG[expr.nama]
        if len(expr.argumen) != len(fungsi.argumen):
            galat.append(f"fungsi {expr.nama} butuh {len(fungsi.argumen)} argumen")
        for a in expr.argumen:
            if not _RE_IDENT.match(a) or a not in ARGUMEN_PROFIL:
                galat.append(f"argumen '{a}' bukan field profil yang dikenal")
    if op == "in" and not isinstance(expr, Daftar):
        galat.append("operator 'in' membutuhkan daftar nilai, mis. SMA|SMK|MA")
    if op != "in" and isinstance(expr, Daftar):
        galat.append("daftar nilai (A|B) hanya untuk operator 'in'")
    if op in _URUTAN and fdef.tipe not in ("int", "float"):
        galat.append(f"operator '{op}' hanya untuk field numerik, '{field}' bertipe {fdef.tipe}")
    if (
        op in _URUTAN
        and isinstance(expr, Literal)
        and (isinstance(expr.nilai, bool) or not isinstance(expr.nilai, (int, float)))
    ):
        galat.append(f"operator '{op}' membutuhkan nilai numerik")
    if (
        fdef.tipe == "bool"
        and op in ("==", "!=")
        and not (isinstance(expr, Literal) and isinstance(expr.nilai, bool))
    ):
        galat.append(f"field boolean '{field}' harus dibandingkan dengan true/false")
    return galat


def evaluasi_nilai(expr: NilaiExpr, k: Konteks) -> Resolved:
    if isinstance(expr, Literal):
        return Resolved(nilai=expr.nilai)
    if isinstance(expr, TahunSiklus):
        return Resolved(nilai=k.tahun_siklus + expr.offset)
    if isinstance(expr, Daftar):
        return Resolved(nilai=expr.item)
    fungsi = FUNGSI_CONFIG[expr.nama]
    nilai_arg: list[Any] = []
    kurang: list[str] = []
    for nama in expr.argumen:
        v = k.profil.get(nama)
        if v is None:
            kurang.append(nama)
        nilai_arg.append(v)
    if kurang:
        return Resolved(kurang=tuple(kurang))
    return Resolved(nilai=fungsi.hitung(k.ketentuan, k.jalur, k.tahun_siklus, *nilai_arg))


def _numerik(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def bandingkan(op: str, kiri: Any, kanan: Any) -> bool:
    """Bandingkan nilai profil (kiri) dengan nilai rule (kanan). Tipe harus cocok, tanpa tebakan."""
    if op == "exists":
        return kiri is not None
    if op == "in":
        return kiri in kanan
    if op in ("==", "!="):
        if isinstance(kiri, bool) != isinstance(kanan, bool):
            raise RuleError(f"Tipe tidak cocok untuk '{op}': {kiri!r} vs {kanan!r}")
        if _numerik(kiri) != _numerik(kanan):
            raise RuleError(f"Tipe tidak cocok untuk '{op}': {kiri!r} vs {kanan!r}")
        sama = kiri == kanan
        return sama if op == "==" else not sama
    if not (_numerik(kiri) and _numerik(kanan)):
        raise RuleError(f"Operator '{op}' butuh angka: {kiri!r} vs {kanan!r}")
    if op == "<=":
        return kiri <= kanan
    if op == ">=":
        return kiri >= kanan
    if op == "<":
        return kiri < kanan
    if op == ">":
        return kiri > kanan
    raise RuleError(f"Operator tidak dikenal: {op}")
