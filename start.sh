#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

print_wizard() {
cat <<'EOF'
              ________
             /\       \
            /  \       \
           /    \       \
          /      \_______\
          \      /       /
        ___\    /   ____/___
       /\   \  /   /\       \
      /  \   \/___/  \       \
     /    \       \   \       \
    /      \_______\   \_______\
    \      /       /   /       /
     \    /       /   /       /
      \  /       /\  /       /
       \/_______/  \/_______/    

        Amber Setup Wizard
       Clean install helper
       
This will:
  1) Check Docker + Compose
  2) Ensure .env exists
  3) Start services
  4) Run database migrations
EOF
}

show_help() {
cat <<'EOF'
Usage: ./start.sh [--gpu]
  --gpu   Enable NVIDIA GPU support
EOF
}

fail() {
  echo ""
  echo "ERROR: $1"
  exit 1
}

check_prereqs() {
  echo ""
  echo "Step 1/4: Checking prerequisites..."
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed. Install Docker Engine + Docker Compose plugin."
  fi
  if ! docker compose version >/dev/null 2>&1; then
    fail "Docker Compose plugin not found. Install 'docker compose'."
  fi
  echo "OK: Docker + Compose"
}

ensure_env() {
  echo ""
  echo "Step 2/4: Checking .env..."
  if [ -f ".env" ]; then
    echo "OK: .env found"
    return 0
  fi
  if [ ! -f ".env.example" ]; then
    fail ".env.example not found; cannot create .env"
  fi
  cp .env.example .env
  echo ""
  echo "Created .env from .env.example."
  echo ""
  echo "Before continuing, edit .env and set at least:"
  echo "  - OPENAI_API_KEY or ANTHROPIC_API_KEY"
  echo "  - SECRET_KEY (generate with: openssl rand -hex 32)"
  echo "  - NEO4J_PASSWORD"
  echo ""
  echo "Then re-run: ./start.sh"
  exit 1
}

wait_for_api() {
  local retries="${1:-60}"
  local sleep_s="${2:-5}"
  local attempt=1

  echo ""
  echo ""
  echo "Step 4/4: Waiting for API health..."
  while [ "$attempt" -le "$retries" ]; do
    if docker compose exec -T api curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
      echo "OK: API is healthy"
      return 0
    fi
    echo "  [$attempt/$retries] API not ready yet..."
    sleep "$sleep_s"
    attempt=$((attempt + 1))
  done
  fail "API did not become healthy. Check logs: docker compose logs api"
}

run_migrations() {
  local retries="${1:-5}"
  local sleep_s="${2:-5}"
  local attempt=1

  echo ""
  echo "Step 3/4: Running migrations..."
  while [ "$attempt" -le "$retries" ]; do
    # Use 'run --rm' to execute migrations in a fresh container, ensuring success even if the main service is crash-looping
    if docker compose run --rm api alembic upgrade head; then
      echo "OK: Migrations complete"
      return 0
    fi
    echo "  Migration attempt $attempt failed; retrying..."
    sleep "$sleep_s"
    attempt=$((attempt + 1))
  done
  fail "Migrations failed. Check logs: docker compose logs api"
}

USE_GPU=false
for arg in "$@"; do
  case "$arg" in
    --gpu)
      USE_GPU=true
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg"
      show_help
      exit 1
      ;;
  esac
done

print_wizard
check_prereqs
ensure_env

# Fix permissions for .cache (Splade models) to prevent PermissionError
# This is needed because the container runs as a non-root user
mkdir -p .cache
sudo chmod -R 777 .cache 2>/dev/null || chmod -R 777 .cache

# Force API to start even if Embeddings are mismatched (allows recovering 'dirty' envs)
if ! grep -q "IGNORE_EMBEDDING_MISMATCH" .env; then
  echo "" >> .env
  echo "# Added by start.sh to allow recovery of mismatched embedding states" >> .env
  echo "IGNORE_EMBEDDING_MISMATCH=true" >> .env
fi

COMPOSE_FILES=(-f docker-compose.yml)
if [ "$USE_GPU" = true ]; then
  echo ""
  echo "GPU mode enabled."
  COMPOSE_FILES+=(-f docker-compose.gpu.yml)
else
  echo ""
  echo "CPU mode enabled."
fi

echo ""
echo "Starting services..."
echo "Command: docker compose ${COMPOSE_FILES[*]} up -d"
docker compose "${COMPOSE_FILES[@]}" up -d

# Run migrations BEFORE waiting for API, so DB is ready
run_migrations 5 5
wait_for_api 60 5

echo ""
echo "Services are up:"
docker compose ps
