# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /src

COPY pyproject.toml uv.lock README.md ./
COPY alembic ./alembic
COPY episodic ./episodic

RUN uv build --wheel --out-dir /dist

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

RUN groupadd --system --gid 10001 episodic \
    && useradd --system --uid 10001 --gid episodic --home-dir /app --shell /usr/sbin/nologin episodic \
    && python -m venv /app/.venv \
    && chown -R episodic:episodic /app

COPY --from=builder /dist/*.whl /tmp/

RUN /app/.venv/bin/python -m pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2).read()"

CMD ["granian", "episodic.api.runtime:create_app_from_env", "--interface", "asgi", "--factory", "--host", "0.0.0.0", "--port", "8080"]
