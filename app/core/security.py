"""Token sesi opaque: acak kriptografis, hanya hash yang disimpan di DB. Tidak ada JWT di MVP."""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32  # 256 bit


def buat_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
