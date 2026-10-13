from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.profile import ProfilePatch

IdProdi = Annotated[str, StringConstraints(min_length=1, max_length=64)]


class PilihanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prodi_id: IdProdi


class StrategyRequest(BaseModel):
    """Evaluasi komposisi satu jalur.

    - `shortlist`: kandidat untuk saran swap (hanya dari sini).
    - `override`: what-if terstruktur (skema sama dengan PUT /profile). Bila ada, `simpan` dipaksa false.
    - `simpan`: simpan pilihan aktif ke `strategies` untuk dipakai /summary.
    """

    model_config = ConfigDict(extra="forbid")

    jalur: Literal["SNBP", "SNBT"]
    pilihan: list[PilihanIn] = Field(min_length=1, max_length=10)
    shortlist: list[IdProdi] = Field(default_factory=list, max_length=30)
    override: ProfilePatch | None = None
    simpan: bool = False

    @field_validator("pilihan")
    @classmethod
    def _tanpa_duplikat(cls, v: list[PilihanIn]) -> list[PilihanIn]:
        ids = [p.prodi_id for p in v]
        ganda = sorted({i for i in ids if ids.count(i) > 1})
        if ganda:
            raise ValueError(f"prodi_id duplikat di pilihan: {', '.join(ganda)}")
        return v

    @field_validator("shortlist")
    @classmethod
    def _shortlist_unik(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))
