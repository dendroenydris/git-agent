#!/bin/bash

# Activate conda environment and start celery worker
set -e

echo "🔧 Starting AutoDev Agent Celery Worker (Conda)..."

# Initialize conda for bash
eval "$(conda shell.bash hook)"

# Activate environment
conda activate autodev-agent-backend

# Determine project root (two levels up from this script)
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Set PYTHONPATH to project root
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# Move to project root to ensure package imports resolve
cd "$PROJECT_ROOT"

# Start celery worker (using fully qualified app path)
python -m celery -A backend.main.celery_app worker --loglevel=info 