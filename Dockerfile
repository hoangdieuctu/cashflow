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

# Create a non-root user and data directory
RUN useradd -m appuser && \
    mkdir -p /data && \
    chown appuser:appuser /data

# Copy the database into the image
COPY techcombank.db /data/techcombank.db
RUN chown appuser:appuser /data/techcombank.db

USER appuser

EXPOSE 5000

ENTRYPOINT ["techcombank-parser", "serve", "--host", "0.0.0.0", "--db", "/data/techcombank.db"]
