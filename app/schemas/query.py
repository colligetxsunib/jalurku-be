"""Skema /query. `extra="forbid"` di SEMUA level: klien tidak boleh mengirim profil/hasil analisis bebas.

Konteks profil dan hasil analisis dibangun SERVER dari id (FR-Q1). Klien hanya mengirim
identifier (`prodi_id`, `jalur`) dan `override` terstruktur untuk what-if.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.profile import ProfilePatch

PANJANG_PERTANYAAN_MAKS = 500


class KonteksQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prodi_id: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    jalur: Literal["SNBP", "SNBT"] | None = None
    override: ProfilePatch | None = None


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pertanyaan: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=PANJANG_PERTANYAAN_MAKS),
    ]
    mode: Literal["tanya", "jelaskan"] = "tanya"
    konteks: KonteksQuery | None = None

    def field_wajib_kurang(self) -> list[str]:
        """Mode 'jelaskan' mewajibkan konteks.prodi_id dan konteks.jalur."""
        if self.mode != "jelaskan":
            return []
        k = self.konteks
        kurang = []
        if k is None or k.prodi_id is None:
            kurang.append("konteks.prodi_id")
        if k is None or k.jalur is None:
            kurang.append("konteks.jalur")
        return kurang
