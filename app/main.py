"""Titik masuk FastAPI. `create_app` menerima dependensi agar mudah diuji."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.api.v1.router import api_router
from app.core.config import (
    AppConfig,
    ConfigError,
    RateLimitConfig,
    Settings,
    get_app_config,
    get_settings,
)
from app.core.errors import register_exception_handlers
from app.core.rate_limit import SlidingWindowLimiter
from app.db.guards import check_embedding_consistency
from app.db.session import make_engine, make_session_factory
from app.db.verifikasi import pastikan_terverifikasi
from app.llm.cache import hapus_kedaluwarsa as hapus_cache_kedaluwarsa
from app.llm.client import LLMClient
from app.llm.service import LLMService, buat_client
from app.services.refdata import RefDataProvider
from app.services.sessions import hapus_kedaluwarsa

log = logging.getLogger("jalurku")


def bersihkan(app: FastAPI) -> int:
    """Hapus sesi kedaluwarsa dan kunci rate limit yang sudah tidak aktif."""
    try:
        n = hapus_kedaluwarsa(app.state.session_factory)
        hapus_cache_kedaluwarsa(app.state.session_factory)
    except Exception as exc:
        log.warning("Pembersihan sesi/cache gagal: %s", type(exc).__name__)
        n = 0
    app.state.limiter.sweep()
    return n


def _pastikan_terverifikasi(app: FastAPI) -> None:
    """REQUIRE_VERIFIED=true: tabel kritis tidak boleh memuat data tanpa tanggal verifikasi."""
    try:
        with app.state.session_factory() as db:
            pastikan_terverifikasi(db)
    except OperationalError:
        log.warning("Database belum terjangkau saat start; pemeriksaan verifikasi data dilewati")


async def _loop_pembersihan(app: FastAPI, interval_detik: float) -> None:
    while True:
        await asyncio.sleep(interval_detik)
        await asyncio.to_thread(bersihkan, app)


def create_app(
    settings: Settings | None = None,
    config: AppConfig | None = None,
    engine: Engine | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    config = config or get_app_config()  # gagal cepat bila config tidak valid
    if settings.trusted_proxies_list:  # env menimpa YAML (CIDR jaringan docker berbeda per server)
        try:
            rl = RateLimitConfig.model_validate(
                {**config.rate_limit.model_dump(), "proxy_tepercaya": settings.trusted_proxies_list}
            )
        except ValidationError as exc:
            raise ConfigError(f"TRUSTED_PROXIES tidak valid: {exc.errors()[0]['msg']}") from exc
        config = config.model_copy(update={"rate_limit": rl})
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            check_embedding_consistency(engine, config)  # ConfigError = gagal start
        except OperationalError:
            log.warning("Database belum terjangkau saat start; guard embedding dilewati")
        if settings.require_verified:
            await asyncio.to_thread(_pastikan_terverifikasi, app)  # ConfigError = gagal start
        await asyncio.to_thread(bersihkan, app)
        tugas = asyncio.create_task(
            _loop_pembersihan(app, config.sesi.interval_pembersihan_menit * 60)
        )
        yield
        tugas.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tugas
        engine.dispose()

    prod = settings.app_env == "prod"
    app = FastAPI(
        title="JalurKu API",
        version="1.0.0",
        docs_url=None if prod else "/docs",
        redoc_url=None,
        openapi_url=None if prod else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.config = config
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.limiter = SlidingWindowLimiter()
    app.state.refdata = RefDataProvider()
    # Satu LLMService per proses: semaphore konkurensi bersifat global (kuota per API key).
    app.state.llm = LLMService(llm_client or buat_client(settings, config), config)

    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


def build_app() -> FastAPI:
    """Factory untuk uvicorn: `uvicorn app.main:build_app --factory`."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return create_app()
