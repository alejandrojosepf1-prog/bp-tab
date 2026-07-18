import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models import Base, User
from app.models.enums import UserRole


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session, mirroring the pattern in `tests/conftest.py`."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """An httpx AsyncClient talking to the real FastAPI app in-process (ASGITransport, no
    real network/socket), with `get_db` overridden to hand back this test's own in-memory
    SQLite session so requests and test-setup code see the same data."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def make_user(
    db_session: AsyncSession,
    *,
    email: str,
    password: str = "password123",
    display_name: str = "Test User",
    role: UserRole = UserRole.USER,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}
