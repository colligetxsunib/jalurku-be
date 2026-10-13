from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class SummaryRequest(BaseModel):
    """`{}` memakai strategi tersimpan terbaru per jalur; `strategy_id` memilih satu strategi."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: uuid.UUID | None = None
