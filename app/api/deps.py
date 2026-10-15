"""Dependensi bersama: autentikasi token sesi dan rate limit."""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import AppConfig, Settings
from app.core.errors import AppError
from app.core.rate_limit import SlidingWindowLimiter, ip_klien, terapkan
from app.db.session import get_db
from app.services.sessions import SesiAktif, cari_sesi_aktif


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_settings_app(request: Request) -> Settings:
    return request.app.state.settings


def get_limiter(request: Request) -> SlidingWindowLimiter:
    return request.app.state.limiter


def _tidak_terautentikasi() -> AppError:
    return AppError(
        "token_tidak_valid",
        "Token tidak ada, tidak valid, atau sesi sudah kedaluwarsa",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _ambil_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    skema, _, token = header.partition(" ")
    if skema.lower() != "bearer" or not token.strip():
        raise _tidak_terautentikasi()
    return token.strip()


def batasi_buat_sesi(
    request: Request,
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> None:
    ip = ip_klien(request, config.rate_limit.proxy_tepercaya)
    terapkan(limiter, f"buat:{ip}", config.rate_limit.buat_sesi_per_ip)


def batasi_ip(
    request: Request,
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> None:
    """Batas per IP untuk endpoint publik tanpa token (kunci sama dengan jalur terautentikasi)."""
    ip = ip_klien(request, config.rate_limit.proxy_tepercaya)
    terapkan(limiter, f"ip:{ip}", config.rate_limit.per_ip)


def sesi_saat_ini(
    request: Request,
    db: Session = Depends(get_db),
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> SesiAktif:
    """Wajib untuk semua endpoint kecuali POST /session dan GET /health."""
    ip = ip_klien(request, config.rate_limit.proxy_tepercaya)
    terapkan(
        limiter, f"ip:{ip}", config.rate_limit.per_ip
    )  # sebelum lookup DB: tumpulkan brute force
    sesi = cari_sesi_aktif(db, _ambil_bearer(request))
    if sesi is None:
        raise _tidak_terautentikasi()
    terapkan(limiter, f"sesi:{sesi.id}", config.rate_limit.per_sesi)
    return sesi


def batasi_llm(
    sesi: SesiAktif = Depends(sesi_saat_ini),
    config: AppConfig = Depends(get_config),
    limiter: SlidingWindowLimiter = Depends(get_limiter),
) -> SesiAktif:
    """Batas lebih ketat untuk endpoint yang memanggil LLM."""
    terapkan(limiter, f"llm:{sesi.id}", config.rate_limit.llm_per_sesi)
    return sesi
