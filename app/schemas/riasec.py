"""Skema tes minat RIASEC. `extra="forbid"` menolak field tak dikenal dengan 422.

Catatan privasi (FR-P4): instrumen hanya mengumpulkan preferensi aktivitas, tanpa identitas.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IdItem = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)]


class RiasecSubmitRequest(BaseModel):
    """Jawaban tes: id item -> nilai skala Likert. Boleh parsial kecuali config menetapkan min_terjawab.

    `simpan=True` menulis vektor minat ke profil sesi (dikonsumsi /explore). `simpan=False` hanya
    menghitung (pratinjau), berguna untuk what-if atau sebelum siswa menyetujui penyimpanan.
    """

    model_config = ConfigDict(extra="forbid")

    jawaban: dict[IdItem, int] = Field(min_length=1)
    simpan: bool = True


class RiasecItemResponse(BaseModel):
    id: str
    dimensi: str
    teks: str


class RiasecQuestionsResponse(BaseModel):
    versi_instrumen: str
    sumber: str
    skala: dict[str, Any]
    min_terjawab: int
    dimensi: list[str]
    item: list[RiasecItemResponse]


class RiasecResultResponse(BaseModel):
    versi_instrumen: str
    skor_norm: dict[str, float]
    skor_mentah: dict[str, int]
    holland_code: str
    dimensi_teratas: list[str]
    jumlah_item: dict[str, int]
    terjawab: int
    total_item: int
    tersimpan: bool
    catatan: str
