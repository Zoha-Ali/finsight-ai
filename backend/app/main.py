from fastapi import FastAPI

from .routes import auth, categorize, data, forecast, qa, receipts, transactions

app = FastAPI(title="FinSight AI")

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(receipts.router)
app.include_router(categorize.router)
app.include_router(forecast.router)
app.include_router(qa.router)
app.include_router(data.router)
