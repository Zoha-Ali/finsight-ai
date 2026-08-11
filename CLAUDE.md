# FinSight AI — Claude Code Instructions

## Project Context

FinSight AI is a multi-agent personal finance assistant built for Arbisoft's 2026 AI Internship, Phase 3.
5 agents: Receipt & Transaction, Categorization & Anomaly, Forecasting, Q&A, Supervisor.
Stack: FastAPI + PostgreSQL (Neon) backend, React/TypeScript frontend, MCP server + supervisor-worker orchestration pattern (reused from Phase 2).

## Prompt Logging (Required)

After every significant prompt/task in this project, automatically append an entry to `prompts.md` at the project root, in this format:

[Date] — [Short task title]
Prompt used: [the prompt/request]
Result: [what was generated/changed, 1-2 lines]
Files affected: [list]

Log entries for: new features, schema/model changes, agent logic, bug fixes, refactors, and architecture decisions. Skip logging for trivial one-line fixes or formatting-only changes.

## Coding Conventions

- Backend: FastAPI, SQLAlchemy (async), Pydantic schemas in `schemas.py`, ruff for linting
- Frontend: React + TypeScript, Tailwind CSS, absolute imports (`@/` alias), components/routes in dedicated folders
- Auth: JWT (bcrypt + SHA-256), reused pattern from prior Todo app work
- Follow existing folder structure under `backend/app/` and `frontend/src/`
