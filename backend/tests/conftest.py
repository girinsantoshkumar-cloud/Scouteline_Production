"""Shared test fixtures and configuration."""
import asyncio
import os
import database
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Set test environment BEFORE importing app modules
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:5433/scoutline_test"
os.environ["GROQ_API_KEY"] = ""
os.environ["SERPAPI_KEY"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["AUTO_MIGRATE"] = "false"

from main import app  # noqa: E402


TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/scoutline_test"


# Create tables synchronously before any async fixtures run
database.settings.database_url = TEST_DATABASE_URL
database._engine = None
database._SessionLocal = None
sync_engine = create_async_engine(TEST_DATABASE_URL, connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0})

async def _create_tables():
    async with sync_engine.begin() as conn:
        from models import Base
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(_create_tables())
asyncio.run(sync_engine.dispose())


@pytest_asyncio.fixture
async def test_engine():
    """Create test database engine."""
    database.settings.database_url = TEST_DATABASE_URL
    database._engine = None
    database._SessionLocal = None
    engine = database.get_engine()
    yield engine
    await engine.dispose()
    database._engine = None
    database._SessionLocal = None


@pytest_asyncio.fixture
async def clean_db(test_engine):
    """Clean all tables before each test."""
    async with test_engine.begin() as conn:
        from models import Base
        from sqlalchemy import text
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f'TRUNCATE TABLE {table.name} RESTART IDENTITY CASCADE'))


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with transaction rollback."""
    database.settings.database_url = TEST_DATABASE_URL
    database._engine = None
    database._SessionLocal = None
    async_session = database.get_session_local()
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def async_client(clean_db) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client with clean database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sample_user_data() -> dict[str, Any]:
    """Sample user data for tests."""
    return {
        "name": "Test User",
        "email": "test@example.com",
        "password": "securepass123",
    }


@pytest.fixture
def sample_search_data() -> dict[str, Any]:
    """Sample search data for tests."""
    return {
        "title": "Python Developer",
        "description": "We are looking for a Python backend developer with experience in FastAPI, REST APIs, PostgreSQL and Docker. Experience building backend applications and real-world software projects is preferred.",
        "count": 10,
    }


@pytest.fixture
async def authenticated_user(async_client: AsyncClient, sample_user_data: dict[str, Any]):
    """Create a registered user and return (client, token)."""
    reg = await async_client.post(
        "/api/auth/register",
        json=sample_user_data,
    )
    assert reg.status_code == 201
    token = reg.json()["token"]
    from httpx import AsyncClient as AsyncClientClass
    auth_client = AsyncClientClass(
        transport=async_client._transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        yield auth_client, token
    finally:
        await auth_client.aclose()
