import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.models import Base, Tournament, User
from app.models.betting import TournamentBalance
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
    tournament: Tournament | None = None,
    balance: float | None = None,
) -> User:
    """`balance=None` leaves no TournamentBalance pre-seeded -- the user gets the real
    STARTING_BALANCE grant the first time they touch `tournament`'s economy (CNADE 2026 Roadmap
    Pieza 3, see bankroll_service.get_or_create_tournament_balance). Pass an explicit `balance`
    (and the `tournament` it applies to) only for tests that need to stake more than that (e.g.
    pool-dynamics tests where the point is large stakes overwhelming the seed), so the grant
    itself can change freely without silently turning those into insufficient-balance failures.
    """
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    if tournament is not None and balance is not None:
        db_session.add(
            TournamentBalance(tournament_id=tournament.id, user_id=user.id, balance=balance)
        )
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


_tournament_seq = 0


async def make_tournament(db_session: AsyncSession, **kwargs) -> Tournament:
    """Unique source_base_url/source_slug per call so tests can create as many as they need
    without colliding on the tournaments table's uniqueness constraint."""
    global _tournament_seq
    _tournament_seq += 1
    kwargs.setdefault("name", f"Test Cup {_tournament_seq}")
    kwargs.setdefault("slug", f"test-cup-{_tournament_seq}")
    kwargs.setdefault("source_base_url", "https://example.calicotab.com")
    kwargs.setdefault("source_slug", f"open-{_tournament_seq}")
    tournament = Tournament(**kwargs)
    db_session.add(tournament)
    await db_session.commit()
    await db_session.refresh(tournament)
    return tournament
