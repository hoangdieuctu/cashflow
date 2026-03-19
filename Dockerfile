FROM python:3.13-slim

WORKDIR /app

# Install build tools needed by some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir .

# Copy the seed database
COPY cashflow.db /app/cashflow.db.seed

# Create a non-root user and data directory
RUN useradd -m appuser && \
    mkdir -p /data && \
    chown appuser:appuser /data /app/cashflow.db.seed

USER appuser

VOLUME /data

EXPOSE 5000

# On first run, copy seed DB to /data if not already present, then serve
ENTRYPOINT ["sh", "-c", "[ ! -f /data/cashflow.db ] && cp /app/cashflow.db.seed /data/cashflow.db; exec cashflow serve --host 0.0.0.0 --db /data/cashflow.db"]
