from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .models import TransactionSource


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TransactionCreate(BaseModel):
    merchant: str
    amount: float
    date: date
    category_id: Optional[int] = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant: str
    amount: float
    date: date
    date_estimated: bool
    source: TransactionSource
    is_anomaly: bool
    is_over_budget: bool
    created_at: datetime
    owner_id: int
    category_id: Optional[int] = None


class CategorizeRequest(BaseModel):
    transaction_id: int


class CategorizeResponse(BaseModel):
    transaction_id: int
    category: str
    category_id: int
    is_anomaly: bool
    reason: Optional[str] = None
    date_estimated: Optional[bool] = None


class ReceiptUploadResponse(BaseModel):
    filename: Optional[str] = None
    type: str
    transactions_created: list[CategorizeResponse]


class ForecastEntry(BaseModel):
    category: str
    spent_so_far: float
    projected_total: float
    budget_limit: Optional[float] = None
    on_track_to_overspend: bool


class ForecastResponse(BaseModel):
    forecasts: list[ForecastEntry]
    summary: str


class QARequest(BaseModel):
    question: str


class QAResponse(BaseModel):
    question: str
    agent_used: str
    result: dict
    trace: list[dict]
    table: Optional[list[dict]] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class BudgetCreate(BaseModel):
    category_id: int
    monthly_limit: float


class BudgetOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    monthly_limit: float


class AnomalyOut(BaseModel):
    id: int
    reason: str
    flagged_at: datetime
    transaction_id: int
    merchant: str
    amount: float
    date: date


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_text: str
    agent_used: str
    steps: list[dict]
    created_at: datetime
