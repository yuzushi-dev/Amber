# =============================================================================
# Amber System - Makefile
# =============================================================================
# Common commands for development, testing, and deployment.
# =============================================================================

.PHONY: help install dev test lint format clean docker-up docker-down docker-build migrate

# Default target
help:
	@echo "Amber System (Hybrid GraphRAG)"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Development:"
	@echo "  install     Install production dependencies"
	@echo "  dev         Install development dependencies"
	@echo "  run         Run the API server locally"
	@echo ""
	@echo "Testing:"
	@echo "  test        Run all tests"
	@echo "  test-unit   Run unit tests only"
	@echo "  test-int    Run integration tests only"
	@echo "  coverage    Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint        Run linter (ruff)"
	@echo "  format      Format code (ruff)"
	@echo "  typecheck   Run type checker (mypy)"
	@echo ""
	@echo "Docker:"
	@echo "  docker-up   Start all services"
	@echo "  docker-down Stop all services"
	@echo "  docker-build Build Docker images"
	@echo "  docker-logs  View service logs"
	@echo ""
	@echo "Database:"
	@echo "  migrate     Run database migrations"
	@echo "  migrate-new Create new migration"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean       Remove build artifacts"

# =============================================================================
# Development
# =============================================================================

install:
	pip install -r requirements.txt

dev:
	pip install -e ".[dev]"

run:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# =============================================================================
# Testing
# =============================================================================

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-int:
	pytest tests/integration/ -v

coverage:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing
	@echo "Coverage report: htmlcov/index.html"

# =============================================================================
# Code Quality
# =============================================================================

lint:
	ruff check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

typecheck:
	mypy src/

# =============================================================================
# Docker
# =============================================================================

docker-up:
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 10
	docker compose ps

docker-down:
	docker compose down

docker-build:
	docker compose build

docker-logs:
	docker compose logs -f

docker-clean:
	docker compose down -v --remove-orphans

# =============================================================================
# Database
# =============================================================================

migrate:
	alembic upgrade head

migrate-new:
	@read -p "Migration message: " msg; \
	alembic revision --autogenerate -m "$$msg"

# =============================================================================
# API Key Management
# =============================================================================

generate-key:
	python -c "from src.shared.security import generate_api_key; print(f'New API key: {generate_api_key()}')"

# =============================================================================
# Cleanup
# =============================================================================

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
