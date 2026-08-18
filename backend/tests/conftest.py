import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import mcp_server as mcp_server_module
from app.agents import categorization_agent as categorization_agent_module
from app.agents import receipt_agent as receipt_agent_module
from app.agents import tracing as tracing_module
from app import database as database_module
from app.auth import create_access_token, hash_password
from app.database import engine
from app.main import app
from app.models import User

# SQLAlchemy's echo=True (set in database.py for dev visibility) drowns
# out test output with every statement executed - quiet it for the test
# run only, this doesn't touch the app's runtime config.
engine.echo = False

# Every module below opened its own `AsyncSessionLocal` at import time
# (`from .database import AsyncSessionLocal`), so patching
# `database_module.AsyncSessionLocal` alone would not affect them - each
# has to be patched individually for a test's DB writes to land on the
# single rolled-back connection instead of the real Neon database.
_SESSION_FACTORY_MODULES = (
    database_module,
    mcp_server_module,
    categorization_agent_module,
    receipt_agent_module,
    tracing_module,
)


@pytest_asyncio.fixture
async def db_conn():
    """A single real DB connection for the test, wrapped in an outer
    transaction that is always rolled back at teardown - this runs
    against the real app models/engine (so schema/constraint behavior is
    real) without ever committing to the actual Neon database.
    """
    async with engine.connect() as conn:
        outer_transaction = await conn.begin()
        yield conn
        await outer_transaction.rollback()


@pytest_asyncio.fixture
async def db_session(db_conn, monkeypatch):
    """A sessionmaker bound to the one test connection via SAVEPOINTs,
    patched into every module that opens sessions on its own - so routes,
    agents, and MCP tool calls exercised during the test all participate
    in the same outer transaction and get rolled back together.
    """
    testing_session_local = async_sessionmaker(
        bind=db_conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    for module in _SESSION_FACTORY_MODULES:
        monkeypatch.setattr(module, "AsyncSessionLocal", testing_session_local)

    async with testing_session_local() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """An httpx client that talks to the FastAPI app in-process (ASGI
    transport, no real network/server) so route tests reuse the same
    rolled-back test transaction as everything else.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(db_session):
    unique = uuid.uuid4().hex[:8]
    user = User(
        username=f"test_user_{unique}",
        email=f"test_user_{unique}@example.com",
        hashed_password=hash_password("correct horse battery staple"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user):
    token = create_access_token(test_user.id, test_user.token_version)
    return {"Authorization": f"Bearer {token}"}
