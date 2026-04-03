FROM python:3.11-slim-bookworm

LABEL maintainer="private" \
      description="WorkMind AI Operational Assistant Node" \
      version="1.0.0"

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN useradd --system --uid 1001 --gid 0 --home /app workmind

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY --chown=1001:0 . .

# ── Persistent volumes ────────────────────────────────────────────────────────
VOLUME ["/app/logs", "/app/data", "/app/reports", "/app/backups"]

# ── Runtime ───────────────────────────────────────────────────────────────────
USER 1001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sys, os; sys.exit(0 if os.path.exists('/app/logs/workmind.log') else 1)"

ENTRYPOINT ["python", "main.py"]
