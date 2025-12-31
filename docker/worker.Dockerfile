# =============================================================================
# Amber Celery Worker Dockerfile
# =============================================================================

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install minimal system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmagic1 \
    file \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy and install requirements
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

# Copy application code
COPY src/ /app/src/
COPY config/ /app/config/

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/uploads && \
    chown -R appuser:appuser /app
USER appuser

# Run Celery worker
CMD ["celery", "-A", "src.workers.celery_app", "worker", "--loglevel=info"]
