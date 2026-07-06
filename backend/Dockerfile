# chefclaw API image. Single-stage (multi-stage not required); init (tini /
# signal handling) is handled by compose.
FROM python:3.13-slim

# uv from the official distroless image, pinned to match the dev machine.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

# ffmpeg: yt-dlp merges Bilibili DASH video+audio streams by spawning it.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependency layer first (cache-friendly), then the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    CHEFCLAW_HOST=0.0.0.0 \
    CHEFCLAW_PORT=8000

EXPOSE 8000

# chefclaw.main runs uvicorn with workers=1 — exactly ONE worker process is a
# hard constraint of the no-broker design (see src/chefclaw/main.py).
CMD ["python", "-m", "chefclaw.main"]
