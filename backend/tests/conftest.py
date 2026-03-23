import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from unittest.mock import AsyncMock, patch

from app.main import app
from app.core.dependencies import get_db
from app.db.base import Base
from app.models.user import User
from app.models.financial_profile import FinancialProfile

# In-memory SQLite for tests — no Docker needed in CI
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """HTTP client with DB and Redis mocked."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    redis_store: dict = {}

    async def mock_setex(key, ttl, value):
        redis_store[key] = value

    async def mock_get(key):
        return redis_store.get(key)

    async def mock_delete(key):
        redis_store.pop(key, None)

    with patch("app.api.v1.auth.redis_client") as mock_redis:
        mock_redis.setex = mock_setex
        mock_redis.get = mock_get
        mock_redis.delete = mock_delete

        with patch("app.api.v1.auth.provision_tenant_schema", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                yield ac

    app.dependency_overrides.clear()