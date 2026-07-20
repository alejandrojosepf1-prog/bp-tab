from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

# statement_cache_size=0 disables asyncpg's server-side prepared-statement cache. Needed for
# any pooled Postgres endpoint (Neon's "-pooler" host, PgBouncer, Supabase's pooler, etc.) in
# transaction-pooling mode: the physical connection backing a given asyncpg session can change
# between statements, so a cached prepared-statement plan from one physical connection can go
# stale on another -- surfacing as `InvalidCachedStatementError` right after any DDL change.
# Harmless against a direct (non-pooled) Postgres connection too, just skips a minor reuse
# optimization there.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0} if "+asyncpg" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with AsyncSessionLocal() as session:
        yield session
