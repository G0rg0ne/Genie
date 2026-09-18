FROM python:3.12-slim

# Install uv by copying the binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1

# Install dependencies first for better layer caching
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

COPY utils/ ./utils/
COPY genie.py ./


ENV FORCE_COLOR=1
ENV LOG_LEVEL=DEBUG

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "genie.py"]
