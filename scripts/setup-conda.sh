#!/bin/bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/backend/environment.yml"
ENV_NAME="${CONDA_ENV_NAME:-autodev-agent-backend}"
FORCE_CONDA_UPDATE="${FORCE_CONDA_UPDATE:-0}"

if ! command -v conda >/dev/null 2>&1; then
  echo "❌ Conda is required but was not found."
  echo "   Install Miniconda or Anaconda first."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Missing conda environment file: $ENV_FILE"
  exit 1
fi

eval "$(conda shell.bash hook)"

if conda env list --json | python -c 'import json, sys; from pathlib import Path; env_name = sys.argv[1]; payload = json.load(sys.stdin); sys.exit(0 if any(Path(prefix).name == env_name for prefix in payload.get("envs", [])) else 1)' "$ENV_NAME" >/dev/null 2>&1; then
  if [ "$FORCE_CONDA_UPDATE" = "1" ]; then
    echo "🔄 Updating conda environment: $ENV_NAME"
    conda env update -n "$ENV_NAME" -f "$ENV_FILE" --prune
  else
    echo "✅ Conda environment already exists: $ENV_NAME"
    echo "   Set FORCE_CONDA_UPDATE=1 to force full environment update."
  fi
else
  echo "🆕 Creating conda environment: $ENV_NAME"
  conda env create -n "$ENV_NAME" -f "$ENV_FILE"
fi

echo "✅ Conda environment ready: $ENV_NAME"
