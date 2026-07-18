import tempfile
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base


@pytest_asyncio.fixture
async def file_db_session_factory():
    """A file-backed (not :memory:) SQLite database, so that a scrape task's own internal
    session (opened via the injected `session_factory`) sees the same rows the test set up
    through a *different* session/connection -- an in-memory SQLite DB is per-connection and
    would otherwise make the two sessions look like two separate empty databases."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        yield session_factory

        await engine.dispose()
