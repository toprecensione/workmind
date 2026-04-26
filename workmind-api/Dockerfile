# WorkMind API — Dockerfile
# Multi-stage build: builder + production image
# Python 3.12-slim base

FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


# ── Builder stage ─────────────────────────────────────────────────────────────
FROM base AS builder
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --prefix=/install .


# ── Production stage ──────────────────────────────────────────────────────────
FROM base AS production
COPY --from=builder /install /usr/local
COPY . .

# Non-root user for security
RUN groupadd -r workmind && useradd -r -g workmind workmind && \
    chown -R workmind:workmind /app
USER workmind

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--loop", "uvloop", "--http", "httptools"]


# ── Development stage (hot-reload) ───────────────────────────────────────────
FROM base AS development
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
