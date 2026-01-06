# =============================================================================
# Amber API Server Dockerfile
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
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy and install requirements
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

# Copy application code
COPY src/ /app/src/
COPY config/ /app/config/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/

# Create non-root user and packages directory
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/.packages && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
