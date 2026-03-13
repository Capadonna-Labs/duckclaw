# Multi-stage build for DuckClaw Core
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and build core
COPY packages/core /app/packages/core
WORKDIR /app/packages/core
RUN pip install .

# Final stage
FROM python:3.11-slim
WORKDIR /app

# Install runtime deps
RUN apt-get update && apt-get install -y \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Environment defaults
ENV DUCKCLAW_DB_PATH="/data/duckclaw.duckdb"
VOLUME /data

CMD ["python"]
