"""Skema tes minat RIASEC (kontrak dengan dashboard/frontend).

Pola id dan `response_model` mengikuti pola dari PR #1 (tanpa mengubah isi respons); tambahan
satu-satunya pada GET adalah `min_terjawab` (aditif). Badan POST tidak berubah.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StringConstraints

PolaId = r"^[a-z][a-z0-9_-]*$"
KunciButir = Annotated[
    str, StringConstraints(pattern=PolaId, min_length=1, max_length=64)
]


class RiasecSubmit(BaseModel):
    """`jawaban` = {id_butir: nilai skala}. Parsial boleh. `simpan=false` = pratinjau tanpa menulis."""

    model_config = ConfigDict(extra="forbid")

    jawaban: dict[KunciButir, StrictInt]
    simpan: StrictBool = True


class ButirOut(BaseModel):
    id: str
    teks: str
    dimensi: str


class SkalaOut(BaseModel):
    min: int
    maks: int
    label: dict[str, str]


class PertanyaanOut(BaseModel):
    versi_instrumen: str
    sumber: str
    instrumen_contoh: bool
    skala: SkalaOut
    dimensi: list[str]
    item: list[ButirOut]
    pernyataan: str
    min_terjawab: int


class HasilOut(BaseModel):
    versi_instrumen: str
    instrumen_contoh: bool
    holland_code: str | None
    dimensi_teratas: list[str]
    skor_norm: dict[str, float]
    terjawab: int
    total_item: int
    terjawab_per_dimensi: dict[str, int]
    dimensi_tidak_dihitung: list[str]
    keyakinan: str
    alasan_keyakinan: list[str]
    tersimpan: bool
    pernyataan: str
    catatan: str
