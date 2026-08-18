from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv
import os
import re

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Neon requires SSL, and asyncpg needs the URL scheme adjusted
# postgresql:// -> postgresql+asyncpg://
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg doesn't accept "sslmode" as a URL query param (that's psycopg2-style);
# strip it out and pass SSL via connect_args instead.
if DATABASE_URL:
    DATABASE_URL = re.sub(
        r"([?&])sslmode=require&?",
        lambda m: m.group(1) if m.group(0).endswith("&") else "",
        DATABASE_URL,
    )

# pool_pre_ping=True (added in af6a126 after real "connection is closed"
# crashes from Neon idle timeouts) validated every single pooled
# connection with a live round trip to Neon before handing it out -
# measured at ~1.2-1.8s of pure network overhead PER DB SESSION (see
# prompts.md's 2026-08-18 performance diagnosis), and since several
# agent/route functions each open their own session, this compounded to
# ~10s of pure overhead on a single /forecast call alone. Replaced with
# pool_recycle rather than dropping the safety net outright, since the
# original crash was real, not hypothetical - but picked a deliberately
# conservative interval rather than pushing close to Neon's commonly-
# documented 5-minute compute-suspend default: pool_recycle=60
# proactively discards and reopens any connection older than 60s on its
# next checkout, so a connection is essentially never given the chance
# to sit idle long enough to hit whatever Neon's actual close threshold
# is (which may be shorter than the compute-suspend timeout - the prior
# incident didn't record the exact trigger). This still avoids pre_ping's
# cost pattern (a live validation on every single checkout) since a
# request only pays the reconnect cost when it happens to land right
# after the 60s mark, not on every request - under normal traffic
# (more than one request per minute) most checkouts hit an already-fresh
# connection. Doesn't catch every possible cause of a dead connection (a
# network blip or an out-of-band Neon restart could still hand out a
# connection that fails on first use, where pre_ping would have caught
# it gracefully) - but that failure mode is rare and self-healing (the
# pool discards a connection that errors on use, so the next request
# gets a fresh one), versus pre_ping's cost being guaranteed on every
# single request regardless of whether anything was ever actually stale.
engine = create_async_engine(
    DATABASE_URL, echo=True, connect_args={"ssl": "require"}, pool_recycle=60
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session