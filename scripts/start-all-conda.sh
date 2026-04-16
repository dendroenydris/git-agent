#!/bin/bash

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

eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"

CONDA_PYTHON="${CONDA_PREFIX}/bin/python"
if [ ! -x "$CONDA_PYTHON" ]; then
  echo "❌ Unable to locate python inside conda env: $ENV_NAME"
  exit 1
fi

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

echo "🐳 Starting PostgreSQL and Redis..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d postgres redis

echo "🚀 Starting API, worker, and frontend..."
cd "$PROJECT_ROOT"
npx concurrently \
  --names "api,worker,web" \
  --prefix-colors "blue,magenta,green" \
  --kill-others-on-fail \
  "$CONDA_PYTHON -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000" \
  "$CONDA_PYTHON -m celery -A backend.main.celery_app worker --loglevel=info" \
  "npm run dev"
