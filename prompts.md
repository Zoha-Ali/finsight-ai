# FinSight AI — Prompt Log

Logging significant AI-assisted prompts throughout Phase 3 development, per internship requirements.

[2026-07-29] — Add SQLAlchemy models
Prompt used: Create backend/app/models.py with SQLAlchemy models for FinSight AI. Models needed: User (id, username, email, hashed_password), Category (id, name), Transaction (id, merchant, amount, date, source ["manual"/"receipt"], is_anomaly bool, is_over_budget bool, created_at, owner_id FK, category_id FK), Budget (id, monthly_limit, owner_id FK, category_id FK), Anomaly (id, reason string, flagged_at, transaction_id FK, owner_id FK). Use owner_id pattern for per-user ownership like the existing Todo app. Import Base from .database. Add appropriate relationships between models.
Result: Defined User, Category, Transaction, Budget, and Anomaly SQLAlchemy models with owner_id-based per-user ownership and relationships between all tables (including a TransactionSource enum for the manual/receipt source field).
Files affected: backend/app/models.py, prompts.md

[2026-07-29] — Set up Alembic (async, no migration run)
Prompt used: Set up Alembic for this project. Initialize Alembic in backend/, configure alembic/env.py to use the async engine and DATABASE_URL from backend/app/database.py (reads from .env via python-dotenv), configure it to autogenerate against Base.metadata from backend/app/models.py. Do NOT run any migration yet, just get the config set up correctly.
Result: Installed alembic + asyncpg, ran `alembic init -t async alembic`, and rewired env.py to reuse the existing async `engine`/`DATABASE_URL` from app.database and target_metadata = Base.metadata (importing app.models so all tables register). alembic.ini's sqlalchemy.url left blank since env.py sets it from .env at runtime. No revisions generated and no migration executed.
Files affected: backend/alembic.ini, backend/alembic/env.py, backend/alembic/script.py.mako, backend/alembic/README, backend/requirements.txt, prompts.md

[2026-07-29] — Fix asyncpg sslmode connection error
Prompt used: Fix backend/app/database.py — the async engine is failing to connect to Neon with TypeError: connect() got an unexpected keyword argument 'sslmode'. Fix by stripping "sslmode=require" out of the DATABASE_URL string (whether it appears as "?sslmode=require" or "&sslmode=require") and passing SSL config via connect_args={"ssl": "require"} in create_async_engine() instead. Keep everything else in the file the same.
Result: Added a regex step that strips "sslmode=require" from DATABASE_URL regardless of its position among query params (sole param, first, middle, or last) without leaving a dangling "?"/"&", and added connect_args={"ssl": "require"} to create_async_engine(). Verified against the real .env value and all param-position variants.
Files affected: backend/app/database.py, prompts.md
