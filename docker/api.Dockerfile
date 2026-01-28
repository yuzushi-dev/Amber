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
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy and install requirements
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

# Optional: Install OCR dependencies (Marker PDF)
# Usage: docker compose build api --build-arg MARKER=true
ARG MARKER=false
COPY requirements-ocr.txt .
RUN if [ "$MARKER" = "true" ]; then \
    echo "Installing Marker OCR dependencies..." && \
    pip install --no-cache-dir -r requirements-ocr.txt; \
    else \
    echo "Skipping Marker OCR (use --build-arg MARKER=true to enable)"; \
    fi

# Copy application code
COPY src/ /app/src/
COPY config/ /app/config/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

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
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
