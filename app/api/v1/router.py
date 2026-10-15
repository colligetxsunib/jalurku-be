from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    analyze,
    catalog,
    explore,
    health,
    profile,
    query,
    riasec,
    session,
    strategy,
    summary,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(session.router)
api_router.include_router(profile.router)
api_router.include_router(catalog.router)
api_router.include_router(riasec.router)
api_router.include_router(explore.router)
api_router.include_router(analyze.router)
api_router.include_router(strategy.router)
api_router.include_router(summary.router)
api_router.include_router(query.router)
api_router.include_router(admin.router)
