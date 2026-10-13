from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.profile import ProfilePatch

JalurLiteral = Literal["SNBP", "SNBT"]


class TargetAnalisis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prodi_id: str = Field(min_length=1, max_length=64)
    jalur: list[JalurLiteral] = Field(min_length=1, max_length=2)

    @field_validator("jalur")
    @classmethod
    def _unik(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class AnalyzeRequest(BaseModel):
    """`override` = what-if terstruktur (skema sama dengan PUT /profile). Tidak pernah disimpan."""

    model_config = ConfigDict(extra="forbid")

    targets: list[TargetAnalisis] = Field(min_length=1, max_length=20)
    override: ProfilePatch | None = None
