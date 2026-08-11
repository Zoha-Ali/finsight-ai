FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

# Apply any pending migrations before serving, then run uvicorn without
# --reload (that flag is for local dev only - it watches the filesystem
# and re-execs the process, which is pointless overhead in a container
# that gets rebuilt on every code change anyway).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
