from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Settings(BaseSettings):
    """Runtime configuration, loaded from backend/.env (see backend/.env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    groq_api_key: str = ""
    # Groq retires models regularly; override with GROQ_MODEL in backend/.env if this one is shut down.
    groq_model: str = "openai/gpt-oss-120b"
    serpapi_key: str = ""
    github_token: str = ""
    cors_origins: str = "http://localhost:5173"

    # PostgreSQL / Supabase connection string. Examples:
    #   Local docker-compose database:
    #     postgresql://postgres:postgres@db:5432/scoutline
    #   Supabase session pooler (port 5432) or transaction pooler (port 6543):
    #     postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
    # NOTE: URL-encode special characters in the password.
    database_url: str = ""

    # Apply Alembic migrations automatically on startup (recommended for a single
    # worker; disable if you run migrations as a separate deploy step).
    auto_migrate: bool = True
    db_echo: bool = False


settings = Settings()


def normalize_database_url(url: str) -> str:
    """Accept ``postgres://`` or ``postgresql://`` and force the async asyncpg driver."""
    url = (url or "").strip()
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


class Base(DeclarativeBase):
    pass


class DatabaseNotConfigured(RuntimeError):
    """Raised when a database connection is requested but DATABASE_URL is empty."""


_engine: AsyncEngine | None = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or lazily create the shared async engine."""
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise DatabaseNotConfigured(
                "Database is not configured. Set DATABASE_URL in backend/.env "
                "(see backend/.env.example) and restart the backend."
            )
        _engine = create_async_engine(
            normalize_database_url(settings.database_url),
            echo=settings.db_echo,
            pool_pre_ping=True,
            pool_recycle=1800,
            # Disable asyncpg's prepared-statement caches so PgBouncer-style poolers
            # (e.g. the Supabase transaction pooler) work.
            connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        )
    return _engine


def get_session_local() -> async_sessionmaker[AsyncSession]:
    """Get or lazily create the session factory bound to the shared engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _SessionLocal


def SessionLocal() -> AsyncSession:  # noqa: N802 - mirrors SQLAlchemy's sessionmaker naming
    """Open a new session: ``async with SessionLocal() as db: ...``."""
    return get_session_local()()


async def dispose_engine() -> None:
    """Close pooled connections (called on application shutdown)."""
    global _engine, _SessionLocal
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _SessionLocal = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    try:
        factory = get_session_local()
    except DatabaseNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    async with factory() as session:
        yield session


__all__ = [
    "Base",
    "DatabaseNotConfigured",
    "Settings",
    "SessionLocal",
    "dispose_engine",
    "get_db",
    "get_engine",
    "get_session_local",
    "normalize_database_url",
    "settings",
]
