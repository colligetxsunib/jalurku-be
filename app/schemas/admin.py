from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    """`payload` berisi baris-baris dengan kolom yang sama seperti berkas CSV seed tipe tersebut."""

    model_config = ConfigDict(extra="forbid")

    tipe: Literal["rules", "ketentuan", "katalog", "acuan", "dokumen", "profesi"]
    payload: list[dict[str, Any]] = Field(max_length=10000)
