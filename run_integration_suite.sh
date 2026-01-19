#!/bin/bash

# Integration Test Suite Runner
# Runs the similarity check and the full ingestion pipeline verification.
# Sets necessary environment variables for local testing with Eager Celery execution.

# Stop on error
set -e

echo "Starting Integration Test Suite..."

# Common Environment Variables
# Common Environment Variables
export REDIS_URL=redis://localhost:6379/0
# Use a separate test database to avoid wiping the production DB
export DATABASE_URL=postgresql+asyncpg://graphrag:graphrag@localhost:5433/graphrag_test
export NEO4J_URI=bolt://localhost:7687
export MILVUS_HOST=localhost
export MINIO_HOST=localhost
export CELERY_BROKER_URL=redis://localhost:6379/1
export CELERY_RESULT_BACKEND=redis://localhost:6379/2
# Force synchronous execution for testing
export CELERY_TASK_ALWAYS_EAGER=True 

# Add current directory to PYTHONPATH for Alembic and tests
export PYTHONPATH=$PYTHONPATH:. 

# Ensure test database exists (Robuster check)
echo "Ensuring test database exists..."
if ! docker exec graphrag-postgres psql -U graphrag -d graphrag -tAc "SELECT 1 FROM pg_database WHERE datname='graphrag_test'" | grep -q 1; then
    docker exec graphrag-postgres psql -U graphrag -d graphrag -c "CREATE DATABASE graphrag_test"
fi

# Apply migrations to the test database
echo "Applying migrations to test database..."
./.venv/bin/alembic upgrade head

# Seed test data (API keys, tenants)
echo "Seeding test data..."
./.venv/bin/python scripts/seed_test_data.py

# 1. Run Similarity Tests (Creating edges between docs)
echo "----------------------------------------------------------------"
echo "Running Similarity Integration Test..."
echo "----------------------------------------------------------------"
./.venv/bin/pytest tests/integration/test_similarity.py -v -s -o log_cli=true -o log_cli_level=INFO

# 2. Run Complete Pipeline Tests (End-to-end ingestion)
echo "----------------------------------------------------------------"
echo "Running Complete Ingestion Pipeline Test..."
echo "----------------------------------------------------------------"
./.venv/bin/pytest tests/integration/test_ingestion_pipeline.py -v -s -o log_cli=true -o log_cli_level=INFO

# 3. Run Chat Pipeline Tests (Retrieval & Generation logic)
echo "----------------------------------------------------------------"
echo "Running Chat Pipeline Integration Test..."
echo "----------------------------------------------------------------"
./.venv/bin/pytest tests/integration/test_chat_pipeline.py -v -s -o log_cli=true -o log_cli_level=INFO

echo "----------------------------------------------------------------"
echo "Integration Test Suite Completed Successfully!"
echo "----------------------------------------------------------------"
