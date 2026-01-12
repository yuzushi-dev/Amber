#!/bin/bash
set -e

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Initialize external resources (Neo4j, Milvus)
echo "Initializing external resources..."
python -m src.scripts.init_resources

# Bootstrap API Key (handled in main.py lifespan, but we ensure DB is ready first)
# No specific command needed here as main.py does it.

# Start the application
echo "Starting application..."
exec "$@"
