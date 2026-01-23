# builder stage
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.7 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT="/usr/local"

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


# final stage
FROM python:3.11-slim-bookworm

# setup
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd -m appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser src /app/src

# runtime config
ENV PORT=8020

USER appuser

EXPOSE 8020

HEALTHCHECK --start-period=20s --interval=30s --timeout=3s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/health')"]

CMD ["sh", "-c", "uvicorn gm.main:app --host 0.0.0.0 --port $PORT"]
