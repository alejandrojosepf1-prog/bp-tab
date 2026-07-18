import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session for fast model/repository-level tests.

    Postgres-only behaviour (native enum types, ON CONFLICT upserts) is exercised separately
    by the integration tests that run against a real Postgres service container.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
