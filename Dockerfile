FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

# Install dependencies
RUN uv sync --frozen

# Expose port
EXPOSE 8020

# Run application
CMD ["uv", "run", "uvicorn", "gm.main:app", "--host", "0.0.0.0", "--port", "8020"]
