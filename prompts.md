# FinSight AI — Prompt Log

Logging significant AI-assisted prompts throughout Phase 3 development, per internship requirements.

[2026-07-29] — Add SQLAlchemy models
Prompt used: Create backend/app/models.py with SQLAlchemy models for FinSight AI. Models needed: User (id, username, email, hashed_password), Category (id, name), Transaction (id, merchant, amount, date, source ["manual"/"receipt"], is_anomaly bool, is_over_budget bool, created_at, owner_id FK, category_id FK), Budget (id, monthly_limit, owner_id FK, category_id FK), Anomaly (id, reason string, flagged_at, transaction_id FK, owner_id FK). Use owner_id pattern for per-user ownership like the existing Todo app. Import Base from .database. Add appropriate relationships between models.
Result: Defined User, Category, Transaction, Budget, and Anomaly SQLAlchemy models with owner_id-based per-user ownership and relationships between all tables (including a TransactionSource enum for the manual/receipt source field).
Files affected: backend/app/models.py, prompts.md
