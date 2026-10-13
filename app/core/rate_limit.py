"""Rate limiting in-memory (cukup untuk satu instance, PRD bagian 13).

Jendela geser per kunci. IP klien dibaca dari X-Forwarded-For hanya bila koneksi langsung berasal
dari proxy tepercaya.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request

from app.core.config import Batas
from app.core.errors import AppError


class SlidingWindowLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._jendela: dict[str, float] = {}
        self._lock = threading.Lock()

    def periksa(self, kunci: str, batas: Batas) -> float | None:
        """Catat satu permintaan. Mengembalikan detik tunggu (Retry-After) bila melebihi batas."""
        sekarang = self._clock()
        with self._lock:
            antrean = self._hits.setdefault(kunci, deque())
            self._jendela[kunci] = batas.jendela_detik
            while antrean and antrean[0] <= sekarang - batas.jendela_detik:
                antrean.popleft()
            if len(antrean) >= batas.maks:
                return max(antrean[0] + batas.jendela_detik - sekarang, 0.001)
            antrean.append(sekarang)
            return None

    def sweep(self) -> int:
        """Buang kunci yang sudah tidak punya permintaan dalam jendelanya."""
        sekarang = self._clock()
        dibuang = 0
        with self._lock:
            for kunci in list(self._hits):
                antrean = self._hits[kunci]
                jendela = self._jendela.get(kunci, 0)
                while antrean and antrean[0] <= sekarang - jendela:
                    antrean.popleft()
                if not antrean:
                    del self._hits[kunci]
                    self._jendela.pop(kunci, None)
                    dibuang += 1
        return dibuang


def _parse_jaringan(daftar: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(x, strict=False) for x in daftar]


def _dalam(ip: str, jaringan: list) -> bool:
    try:
        alamat = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(alamat in n for n in jaringan)


def ip_klien(request: Request, proxy_tepercaya: list[str]) -> str:
    """IP klien. X-Forwarded-For dipercaya hanya bila koneksi langsung dari proxy tepercaya."""
    langsung = request.client.host if request.client else "unknown"
    if not proxy_tepercaya or not _dalam(langsung, _parse_jaringan(proxy_tepercaya)):
        return langsung
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return langsung
    jaringan = _parse_jaringan(proxy_tepercaya)
    # Telusuri dari kanan: IP pertama yang bukan proxy tepercaya adalah klien sebenarnya.
    for kandidat in reversed([x.strip() for x in xff.split(",") if x.strip()]):
        if not _dalam(kandidat, jaringan):
            return kandidat
    return langsung


def terapkan(limiter: SlidingWindowLimiter, kunci: str, batas: Batas) -> None:
    tunggu = limiter.periksa(kunci, batas)
    if tunggu is not None:
        raise AppError(
            "terlalu_banyak_permintaan",
            "Terlalu banyak permintaan. Coba lagi beberapa saat lagi.",
            status_code=429,
            headers={"Retry-After": str(max(1, math.ceil(tunggu)))},
        )
