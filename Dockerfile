FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata and source
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY config/ ./config/

# Install package in editable mode
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

VOLUME ["/data"]

ENTRYPOINT ["healthcli"]
