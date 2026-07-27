# syntax=docker/dockerfile:1

# --- build -------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependencies resolve from the lockfile alone, so this layer is cached until
# pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- runtime -----------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 kira

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=kira:kira /app/.venv /app/.venv
COPY --chown=kira:kira agent/ ./agent/
COPY --chown=kira:kira api/ ./api/

# company_brain/ is deliberately NOT copied. It is mounted at runtime so a
# policy version can be swapped without rebuilding or restarting the image.

USER kira
EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
