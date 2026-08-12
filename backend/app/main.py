import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import auth, categorize, data, forecast, qa, receipts, transactions

app = FastAPI(title="FinSight AI")

# Same two origins as always for local dev (npm run dev on 5173). A
# containerized frontend served on a different port - e.g. via nginx on
# something other than the 5173 docker-compose.yml maps by default -
# needs its own origin added here; CORS_ORIGINS lets that be configured
# without touching code, comma-separated, e.g.
# "http://localhost:5173,http://localhost:80".
_default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_configured_origins = os.getenv("CORS_ORIGINS")
allow_origins = (
    [origin.strip() for origin in _configured_origins.split(",") if origin.strip()]
    if _configured_origins
    else _default_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    # Vercel gives every deploy its own URL - the production domain plus a
    # fresh, randomly-hashed one per preview deployment - so a static list
    # can't keep up. Regex-matching any *.vercel.app origin (in addition to
    # the explicit allow_origins above) covers all of them, current and
    # future, without needing a code change or Railway env var update per
    # deploy.
    allow_origin_regex=r"https://.*\.vercel\.app",
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
