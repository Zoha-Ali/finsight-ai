import enum
from datetime import date as date_, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from .database import Base


class TransactionSource(str, enum.Enum):
    manual = "manual"
    receipt = "receipt"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    # Bumped on logout - every access/refresh token embeds the version it
    # was issued under, and get_current_user/the refresh endpoint reject a
    # token whose version doesn't match the user's current one. This
    # invalidates every token issued before the bump, across every
    # device/session, without needing a revocation table.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    transactions = relationship("Transaction", back_populates="owner", cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="owner", cascade="all, delete-orphan")
    anomalies = relationship("Anomaly", back_populates="owner", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)

    transactions = relationship("Transaction", back_populates="category")
    budgets = relationship("Budget", back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    merchant = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(Date, nullable=False, default=date_.today)
    date_estimated = Column(Boolean, nullable=False, default=False)
    source = Column(Enum(TransactionSource), nullable=False, default=TransactionSource.manual)
    is_anomaly = Column(Boolean, nullable=False, default=False)
    is_over_budget = Column(Boolean, nullable=False, default=False)
    categorized_by_model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)

    owner = relationship("User", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    anomaly = relationship("Anomaly", back_populates="transaction", uselist=False, cascade="all, delete-orphan")


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True, index=True)
    monthly_limit = Column(Float, nullable=False)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)

    owner = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    reason = Column(String, nullable=False)
    flagged_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    transaction = relationship("Transaction", back_populates="anomaly")
    owner = relationship("User", back_populates="anomalies")


class Trace(Base):
    __tablename__ = "traces"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    request_text = Column(String, nullable=False)
    agent_used = Column(String, nullable=False)
    steps = Column(JSON, nullable=False)  # the trace list (agent name, input, output per step)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
