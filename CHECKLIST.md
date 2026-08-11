# FinSight AI — Roadmap Checklist

## Week 5 (second half) — Scaffold & Architecture
- [x] GitHub repo with scaffold
- [x] Data models (User, Category, Transaction, Budget, Anomaly)
- [x] Alembic migrations applied
- [x] JWT auth (get_current_user)
- [x] Stub routes for 5 agent endpoints
- [x] README with architecture diagram
- [x] Frontend skeleton (routes stubbed)

## Week 6 — Core Feature Development
- [x] Core business logic (real transaction CRUD, not stubs) — `POST/GET/DELETE /transactions` fully implemented and tested, not stubs
- [x] MCP server implementation (7 tools: `get_transactions`, `record_transaction`, `get_budget`, `get_monthly_summary`, `get_historical_monthly_average`, `get_weekly_average`, `get_anomalies`) — exceeds the original 5-tool plan
- [x] Supervisor + 4 worker agents implemented (Receipt & Transaction, Categorization & Anomaly, Forecasting, Q&A) — 5 agents total including the Supervisor, matching the README's architecture
- [ ] Memory layer integrated — not built; each agent call is stateless aside from the `Trace` log (see below)
- [x] Frontend wired to live backend
- [x] Test suite (84 tests, all passing, 66% overall coverage; every priority area — auth, models, forecasting math, categorization anomaly logic, route auth, budget upsert — exceeds the 70% target, several at 100%)

## Week 7 — Advanced Features & Polish
- [x] Secondary AI feature (advanced forecasting) — historical-average fallback baseline when no budget is set, plus weekly-average-based anomaly detection (replacing a simpler recent-transaction-average baseline)
- [x] Multi-model routing (2+ LLM providers/models active) — Anthropic (Sonnet, for complex Q&A) + Groq/Llama 3.3 70B (for categorization and simple Q&A), chosen per-request by the Supervisor's complexity classification; also a manual Compare Models mode (Haiku vs Sonnet side by side) on the Chat page
- [ ] Output validation (schema guards, retry logic) — partial: Pydantic schemas guard every API request/response boundary, and the Receipt Agent retries once on invalid JSON from the model, but this retry pattern isn't applied consistently across the other agents yet
- [x] UX polish (loading/error/empty states) — loading indicators, disabled-during-request inputs, error banners, and empty states are implemented across Dashboard, Forecast, and Chat
- [ ] Deployment (containerized or hosted) — not started, no Dockerfile or hosting config yet
- [ ] Draft presentation slides

## Week 8 — Finalization & Presentation
- [ ] Code freeze, bug fixes only
- [ ] Complete README + docs — README.md and this checklist were refreshed to match the current codebase (2026-08-06); leaving unchecked since this is a Week 8 finalization pass, not a one-time sync
- [ ] prompts.md finalized
- [ ] Final presentation prepared
- [ ] Demo video recorded (5 min)
- [ ] Reflection doc

## Daily Log

| Date | Tasks Completed | Notes |
|---|---|---|
| | | |
