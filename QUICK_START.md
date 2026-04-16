# Quick Start

## Fastest Path

If you want the whole stack with PostgreSQL, Redis, API, worker, and frontend:

```bash
npm install
npm run conda:setup
npm run dev:all-conda
```

Open:

- `http://localhost:3000` for the dashboard
- `http://localhost:8000/health` for backend health

## Manual Local Run

### 1. Frontend

```bash
npm install
npm run dev
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Worker

```bash
python -m celery -A backend.main.celery_app worker --loglevel=info
```

### 4. Infrastructure

Start Redis and PostgreSQL separately, or let Docker Compose manage them:

```bash
docker compose up postgres redis
```

## Required Environment Variables

Backend:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/git_rag
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=
GITHUB_TOKEN=
```

Frontend `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

## What Works In The MVP

- create dialogs for GitHub repositories
- send natural-language requests
- plan multi-step workflows with typed task steps
- pause for human approval on risky actions
- stream task updates to the frontend
- persist dialogs/tasks in the database
- use PAT-backed GitHub comment and workflow-dispatch primitives

## Validation Commands

```bash
npm run build
./scripts/setup-conda.sh
python start_debug_backend.py
```