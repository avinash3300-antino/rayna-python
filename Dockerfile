# ─────────────────────────────────────────────────────────
# Multi-stage production build — python:3.12-slim
# ─────────────────────────────────────────────────────────

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./

# Install production dependencies into a virtual environment
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache .

# Stage 2: Production image
FROM python:3.12-slim AS production

WORKDIR /app

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/
# RUN mkdir -p ./data
# COPY data/ ./data/

# Non-root user
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

ENV PORT=3001
EXPOSE ${PORT}

# Run with uvicorn — uses PORT env var so Render/Railway can override it
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
