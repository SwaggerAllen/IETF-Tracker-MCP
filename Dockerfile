# Multi-stage build for the App Platform `api` component.
#
# NOTE: scaffolding for the target structure. Not buildable until the React SPA
# (frontend/) and the FastAPI app (wgtracker.api.app) land in Milestone 2. CI
# does not build this image yet; the deploy workflow only runs on main.

# --- Stage 1: build the React SPA ---
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime ---
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY src/ ./src/
RUN uv pip install --system --no-cache .

COPY config.yaml alembic.ini ./
COPY migrations/ ./migrations/
COPY --from=frontend /frontend/dist ./static/

EXPOSE 8080
CMD ["uvicorn", "wgtracker.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
