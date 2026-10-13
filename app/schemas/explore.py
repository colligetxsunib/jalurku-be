from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExploreRequest(BaseModel):
    """`{}` memakai top_n bawaan dari config. `jalur` opsional: bila ada, tiap rekomendasi memuat kelayakan."""

    model_config = ConfigDict(extra="forbid")

    top_n: int | None = Field(default=None, ge=1, le=20)
    jalur: Literal["SNBP", "SNBT"] | None = None
