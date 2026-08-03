from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import auth, categorize, data, forecast, qa, receipts, transactions

app = FastAPI(title="FinSight AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(receipts.router)
app.include_router(categorize.router)
app.include_router(forecast.router)
app.include_router(qa.router)
app.include_router(data.router)
