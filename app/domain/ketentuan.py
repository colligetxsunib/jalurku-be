"""Ketentuan resmi SNPMB per siklus (isi config_ketentuan.csv). Fungsi murni, tanpa DB."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class RuleError(Exception):
    """Rule atau ketentuan tidak bisa dievaluasi (data salah, bukan kesalahan siswa)."""


class KetentuanHilang(RuleError):
    pass


@dataclass(frozen=True)
class Ketentuan:
    """Peta (key, jalur, tahun_siklus) -> nilai mentah. Jalur 'ALL' menjadi cadangan."""

    item: Mapping[tuple[str, str, int], str] = field(default_factory=dict)
    terstruktur: Mapping[tuple[str, str, int], Any] = field(default_factory=dict)

    @classmethod
    def dari_baris(cls, baris: Iterable[Mapping[str, Any]]) -> Ketentuan:
        item: dict[tuple[str, str, int], str] = {}
        terstruktur: dict[tuple[str, str, int], Any] = {}
        for b in baris:
            kunci = (str(b["key"]), str(b["jalur"]), int(b["tahun_siklus"]))
            item[kunci] = str(b["nilai"])
            if b.get("nilai_terstruktur") is not None:
                terstruktur[kunci] = b["nilai_terstruktur"]
        return cls(item, terstruktur)

    def _cari(self, sumber: Mapping, key: str, jalur: str, tahun: int) -> Any:
        for j in (jalur, "ALL"):
            if (key, j, tahun) in sumber:
                return sumber[(key, j, tahun)]
        return None

    def nilai(self, key: str, jalur: str, tahun_siklus: int) -> str:
        v = self._cari(self.item, key, jalur, tahun_siklus)
        if v is None:
            raise KetentuanHilang(f"Ketentuan '{key}' ({jalur}, {tahun_siklus}) tidak ditemukan")
        return v

    def angka(self, key: str, jalur: str, tahun_siklus: int) -> float:
        mentah = self.nilai(key, jalur, tahun_siklus)
        try:
            return float(mentah)
        except ValueError as exc:
            raise RuleError(f"Ketentuan '{key}' bukan angka: {mentah!r}") from exc

    def struktur(self, key: str, jalur: str, tahun_siklus: int) -> Any:
        v = self._cari(self.terstruktur, key, jalur, tahun_siklus)
        if v is None:
            raise KetentuanHilang(
                f"Ketentuan terstruktur '{key}' ({jalur}, {tahun_siklus}) tidak ditemukan"
            )
        return v

    def punya(self, key: str, jalur: str, tahun_siklus: int) -> bool:
        return self._cari(self.item, key, jalur, tahun_siklus) is not None
