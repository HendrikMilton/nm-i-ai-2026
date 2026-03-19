FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml .
RUN uv sync --no-dev

COPY ../shared /app/shared
COPY . /app/

EXPOSE 4001
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4001"]
