<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.44.27.png" width="900" alt="AutoDev Agent dashboard" />
</p>

<p align="center">
  <em>Plan, approve, and run repository-aware DevOps workflows from a live agent console.</em>
</p>

<p align="center">
  <img alt="Node version" src="https://img.shields.io/badge/node-%3E%3D18.17-339933?logo=node.js&logoColor=white" />
  <img alt="Python version" src="https://img.shields.io/badge/python-%3E%3D3.10-3776AB?logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="Next.js" src="https://img.shields.io/badge/frontend-Next.js-000000?logo=next.js&logoColor=white" />
  <img alt="Redis" src="https://img.shields.io/badge/events-Redis-DC382D?logo=redis&logoColor=white" />
  <img alt="Postgres" src="https://img.shields.io/badge/db-PostgreSQL-4169E1?logo=postgresql&logoColor=white" />
</p>

<p align="center">
  <a href="#-demo">Demo</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-what-it-does">What It Does</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-quick-start">Quick Start</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-architecture">Architecture</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-validation">Validation</a>
</p>

# AI DevOps Copilot

This project packages an agentic RAG DevOps copilot as a full-stack app with a live operator console.

It lets an operator point the system at a GitHub repository, ask for a DevOps task in natural language, review the plan, approve risky actions, and watch execution updates stream back into the UI.

## ✨ What It Does

- Uses `FastAPI` for API routes, dialog state, approvals, and websocket streaming.
- Uses `Celery + Redis` for background task execution and event fan-out.
- Uses `LangChain`-backed planning plus repository indexing for context-aware steps.
- Uses `Chroma` to index repository content for retrieval-augmented answers and planning.
- Uses `Next.js + Tailwind CSS` to render the operator console, task trace, and chat workflow.
- Uses a GitHub PAT to support repo metadata access, comments, workflow dispatch, and PR helpers.

## 🖼 Demo

<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.42.42.png" width="48%" alt="Main workflow console" />
  <img src="pics/Screenshot%202025-07-08%20at%2022.42.45.png" width="48%" alt="Repository switch modal" />
</p>
<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.43.04.png" width="48%" alt="Expanded workflow and terminal" />
  <img src="pics/Screenshot%202025-07-08%20at%2022.44.27.png" width="48%" alt="Notebook and task history flow" />
</p>

The UI centers around three moving parts:

- A left rail for repository context and task history.
- A middle panel for the execution plan, step output, and terminal view.
- A right rail for dialog history, operator prompts, and agent responses.

## 🚀 Quick Start

### Prerequisites

- Node.js `18.17+`
- Python `3.10+`
- Redis
- PostgreSQL
- Git
- Optional but recommended:
  - `OPENAI_API_KEY` for model-backed planning and summaries
  - `GITHUB_TOKEN` for private repo access and GitHub write actions

### 1. Install frontend dependencies

```bash
npm install
```

### 2. Configure frontend environment

Create `.env.local` in the project root:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

### 3. Configure backend environment

Set backend environment variables:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/git_rag
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=
GITHUB_TOKEN=
LOG_LEVEL=INFO
```

### 4. Start the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start the worker

```bash
python -m celery -A backend.main.celery_app worker --loglevel=info
```

### 6. Start the frontend

```bash
npm run dev
```

Open `http://localhost:3000` and start a dialog against a GitHub repository.

## 🐳 Docker Compose

If you want the full stack up in one shot:

```bash
npm run compose:up
```

This starts:

- `frontend` on `http://localhost:3000`
- `api` on `http://localhost:8000`
- `worker`
- `postgres`
- `redis`

To stop and remove volumes:

```bash
npm run compose:down
```

## 🧠 Workflow

1. Create or select a dialog bound to a GitHub repository.
2. Send a natural-language DevOps request.
3. The backend decides whether to answer directly or create a durable task run.
4. If needed, the repository gets indexed and the planner produces the next executable steps.
5. Approval-gated actions pause until an operator approves or rejects them.
6. The worker executes shell, Docker, or GitHub actions and streams status back through Redis and websockets.
7. The UI shows live trace entries, step output, approval state, and the final summary.

## 🏗 Architecture

### Backend

- `backend/main.py`: compatibility entrypoint that exposes the FastAPI app and Celery instance.
- `backend/app/main.py`: API routes, websocket handling, health checks, and approval endpoints.
- `backend/app/agents/`: orchestration core plus planner context, execution facts, and trace shaping.
- `backend/app/rag/`: repository indexing and retrieval.
- `backend/app/services/`: chat flow, dialogs, task updates, events, settings, and GitHub integration.
- `backend/app/workers/`: Celery app and job entrypoints.
- `backend/app/executors/`: local execution boundary with room for a future sandbox runner.

### Frontend

- `app/page.tsx`: main console shell.
- `app/components/`: task workflow, sidebars, top bar, and settings modal.
- `app/hooks/useWebSocket.ts`: live event stream handling.
- `app/hooks/useConsoleState.ts`: dialog and task selection state.
- `app/lib/api.ts`: API client and shared UI types.

## 🔌 API Surface

- `GET /health`
- `POST /api/dialogs`
- `GET /api/dialogs`
- `GET /api/dialogs/{dialog_id}`
- `POST /api/dialogs/{dialog_id}/chat`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/approval`
- `POST /api/tasks/{task_id}/replan`
- `POST /api/repositories/{dialog_id}/index`
- `GET /api/tools`
- `WS /ws/{dialog_id}`

## 🛡 Safety Model

- Shell execution goes through an allowlist.
- Dangerous command fragments are blocked before execution.
- Shell, Docker, and GitHub write actions can require explicit human approval.
- The execution layer keeps a replaceable boundary for a future sandbox runner.

## 🧰 Tech Stack

- Frontend: `Next.js 14`, `React 18`, `Tailwind CSS`, `TanStack Query`
- Backend: `FastAPI`, `SQLAlchemy`, `Pydantic`
- Async work: `Celery`, `Redis`
- LLM and retrieval: `LangChain`, `Chroma`
- Storage: `PostgreSQL`

## ✅ Validation

Frontend checks:

```bash
npm run lint
npm run build
```

Backend checks:

```bash
python3 -m compileall backend/app
```