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

engine = create_async_engine(
    DATABASE_URL, echo=True, connect_args={"ssl": "require"}, pool_pre_ping=True
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session