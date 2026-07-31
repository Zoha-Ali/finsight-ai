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

[2026-07-30] — Rewrite auth.py (self-contained JWT + bcrypt)
Prompt used: Rewrite backend/app/auth.py completely (self-contained, don't rely on any other project's auth code). Include password hashing (bcrypt + SHA-256 pre-hash), create_access_token() (2 day expiry) / create_refresh_token() (5 day expiry), decode_token() raising 401 on invalid/expired tokens, and a get_current_user() FastAPI dependency (Bearer token -> decode -> look up user by "sub" via get_db -> 401 if not found, else return User). SECRET_KEY loaded from .env via os.getenv, load_dotenv() called the same way as database.py. Add SECRET_KEY to backend/.env with a random generated value; confirm .gitignore already covers .env.
Result: Rewrote auth.py using bcrypt (direct, not passlib) for hashing with a SHA-256 pre-hash to avoid bcrypt's 72-byte input limit, PyJWT for create_access_token/create_refresh_token/decode_token, and an OAuth2PasswordBearer-based get_current_user() dependency querying User by the "sub" claim via get_db. Generated a random 32-byte hex SECRET_KEY into backend/.env (already git-ignored via .gitignore:2) and added bcrypt/PyJWT to requirements.txt. Verified with a smoke test: long-password hashing/verification, access vs refresh token expiry delta (3 days), and 401 on an invalid token.
Files affected: backend/app/auth.py, backend/.env, backend/requirements.txt, prompts.md

[2026-07-31] — Stub agent routes + wire into main.py
Prompt used: Create stub route files under backend/app/routes/ for FinSight AI's 5 agent-related endpoints (transactions.py: POST/GET /transactions; receipts.py: POST /receipts/upload; categorize.py: POST /categorize; forecast.py: GET /forecast; qa.py: POST /qa), each a properly structured FastAPI router with placeholder/mock logic. Wire all routers into main.py. Protect every route with get_current_user from auth.py via Depends(), owner-scoped like the Todo app.
Result: Added Pydantic schemas (TransactionCreate/Out, ReceiptUploadResponse, CategorizeRequest/Response, ForecastPoint/Response, QARequest/Response) to schemas.py, and 5 APIRouter modules under app/routes/ returning mock data (owner_id sourced from the authenticated user, no real agent/DB logic yet). Built app in main.py and included all 5 routers. Verified: all 6 endpoints appear in the OpenAPI schema, unauthenticated requests return 401, and an authenticated-but-nonexistent-user token correctly reaches the real DB via get_current_user and 401s with "User not found."
Files affected: backend/app/schemas.py, backend/app/routes/transactions.py, backend/app/routes/receipts.py, backend/app/routes/categorize.py, backend/app/routes/forecast.py, backend/app/routes/qa.py, backend/app/main.py, prompts.md

[2026-07-31] — Add project README
Prompt used: Create a README.md at the project root for FinSight AI, including project overview, a mermaid architecture flowchart (Frontend -> Backend API -> Supervisor -> 5 worker agents -> MCP server -> PostgreSQL), a tech stack table, model selection rationale (claude-haiku-4-5 for routine agent tasks, vision API for receipt parsing), setup instructions, and current status (built vs next).
Result: Added README.md with all 6 requested sections, kept scannable/concise.
Files affected: README.md, prompts.md
