#!/bin/bash

# Hard failures only for the preflight section; concurrently manages its own processes.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_NAME="${CONDA_ENV_NAME:-autodev-agent-backend}"

if ! command -v conda >/dev/null 2>&1; then
  echo "❌ Conda is required but was not found."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker is required to start PostgreSQL and Redis."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm is required but was not found."
  exit 1
fi

if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
  echo "📦 Installing frontend dependencies..."
  npm install --prefix "$PROJECT_ROOT"
fi

echo "🔧 Ensuring conda environment exists..."
"$PROJECT_ROOT/scripts/setup-conda.sh"

# conda shell hook can emit non-zero on some setups; allow it.
set +e
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"
set -e

CONDA_PYTHON="${CONDA_PREFIX}/bin/python"
if [ ! -x "$CONDA_PYTHON" ]; then
  echo "❌ Unable to locate python inside conda env: $ENV_NAME"
  exit 1
fi

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

# Load local secrets so uvicorn/celery inherit OPENAI_API_KEY, GITHUB_TOKEN, etc.
ENV_FILE="$PROJECT_ROOT/backend/.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# Kill any stale processes holding the ports we need, so restarts are clean.
for port in 8000 3000; do
  pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "🔪 Killing existing process on port $port (pid $pid)..."
    kill -9 $pid 2>/dev/null || true
    sleep 0.5
  fi
done

echo "🐳 Starting PostgreSQL and Redis..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d postgres redis

# Wait for postgres to accept connections before letting the backend try to
# create tables. On a cold Docker volume this can take 3-8 seconds.
echo "⏳ Waiting for PostgreSQL to be ready..."
max_attempts=30
attempt=0
until docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T postgres \
    pg_isready -U postgres -d git_rag -q 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "❌ PostgreSQL did not become ready in time."
    exit 1
  fi
  sleep 1
done
echo "✅ PostgreSQL ready."

echo "🚀 Starting API, worker, and frontend..."
cd "$PROJECT_ROOT"
npx concurrently \
  --names "api,worker,web" \
  --prefix-colors "blue,magenta,green" \
  --kill-others-on-fail \
  "$CONDA_PYTHON -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000" \
  "$CONDA_PYTHON -m celery -A backend.main.celery_app worker --loglevel=info" \
  "npm run dev"
