from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .models import TransactionSource


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
    source: TransactionSource
    is_anomaly: bool
    is_over_budget: bool
    created_at: datetime
    owner_id: int
    category_id: Optional[int] = None


class ReceiptUploadResponse(BaseModel):
    filename: str
    status: str
    transaction: Optional[TransactionOut] = None


class CategorizeRequest(BaseModel):
    transaction_id: int


class CategorizeResponse(BaseModel):
    transaction_id: int
    predicted_category: str
    confidence: float


class ForecastPoint(BaseModel):
    month: str
    predicted_spend: float


class ForecastResponse(BaseModel):
    owner_id: int
    forecast: list[ForecastPoint]


class QARequest(BaseModel):
    question: str


class QAResponse(BaseModel):
    question: str
    answer: str
