FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libportaudio2 \
        portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/

RUN uv sync --no-dev

ENV SHADOW_CLERK_DATA_DIR=/data

EXPOSE 8765

ENTRYPOINT ["uv", "run", "clerk-daemon", "--dashboard-host", "0.0.0.0"]
