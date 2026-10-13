"""Engine dan sesi SQLAlchemy (sinkron, psycopg3)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str, *, connect_timeout: int = 5) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": connect_timeout},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """Dependensi FastAPI: satu sesi DB per request, commit dilakukan eksplisit oleh pemanggil."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    db = factory()
    try:
        yield db
    finally:
        db.close()
