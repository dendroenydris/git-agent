#!/bin/bash

# Activate conda environment and start development server
set -e

echo "🚀 Starting AutoDev Agent Backend (Conda)..."

# Initialize conda for bash
eval "$(conda shell.bash hook)"

# Activate environment
conda activate autodev-agent-backend

# Determine project root (this script is inside backend/scripts)
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Set PYTHONPATH to project root
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH}"

# Move to project root so package imports resolve
cd "$PROJECT_ROOT"

# Start development server
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000