<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.44.27.png" width="900" alt="AI DevOps Copilot" />
</p>

<p align="center">
  <em>Point it at a repo, describe a DevOps task, review the plan, and watch it run.</em>
</p>

<p align="center">
  <img alt="Node" src="https://img.shields.io/badge/node-%3E%3D18.17-339933?logo=node.js&logoColor=white" />
  <img alt="Python" src="https://img.shields.io/badge/python-%3E%3D3.10-3776AB?logo=python&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" />
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-000000?logo=next.js&logoColor=white" />
  <img alt="Redis" src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white" />
  <img alt="Postgres" src="https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white" />
</p>

<p align="center">
  <a href="#-demo">Demo</a>
  &nbsp;•&nbsp;
  <a href="#-getting-started">Getting Started</a>
  &nbsp;•&nbsp;
  <a href="#-how-it-works">How It Works</a>
  &nbsp;•&nbsp;
  <a href="#-tech-stack">Tech Stack</a>
</p>

# AI DevOps Copilot

An agentic DevOps assistant with a live operator console. Connect it to a GitHub repository, ask for something in plain English, and it will plan the work, ask for approval on anything risky, and execute — streaming trace output back as it goes.

---

## 🖼 Demo

<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.42.42.png" width="48%" alt="Main workflow console" />
  <img src="pics/Screenshot%202025-07-08%20at%2022.42.45.png" width="48%" alt="Repository switch" />
</p>
<p align="center">
  <img src="pics/Screenshot%202025-07-08%20at%2022.43.04.png" width="48%" alt="Step output and trace" />
  <img src="pics/Screenshot%202025-07-08%20at%2022.44.27.png" width="48%" alt="Task history" />
</p>

The console has three panels: repository context and task history on the left, the execution plan and live step output in the middle, and the dialog thread on the right.

---

## 👨‍💻 Getting Started

### Prerequisites

- [Node.js](https://nodejs.org/) `18.17+`
- [Python](https://www.python.org/) `3.10+` — via [conda](https://docs.conda.io/en/latest/miniconda.html) (recommended) or a plain venv
- [Docker](https://www.docker.com/products/docker-desktop) — for PostgreSQL and Redis
- `OPENAI_API_KEY` — for planning and summaries
- `GITHUB_TOKEN` — optional, needed for private repos and GitHub write actions

### Quickest path (conda)

Clone, drop your keys into `backend/.env`, and run one script:

```bash
git clone https://github.com/dendroenydris/git-agent.git
cd git-agent
cp backend/.env.example backend/.env   # fill in OPENAI_API_KEY and GITHUB_TOKEN
./scripts/start-all-conda.sh
```

That script will create the conda env if needed, start Postgres and Redis in Docker, wait for them to be ready, then launch the API, Celery worker, and Next.js dev server together. Open [http://localhost:3000](http://localhost:3000).

### Manual setup

<details>
<summary>Expand for manual steps</summary>

**Backend**

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd ..

# in one terminal
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# in another
python -m celery -A backend.main.celery_app worker --loglevel=info
```

**Frontend**

```bash
npm install
# create .env.local with NEXT_PUBLIC_API_URL and NEXT_PUBLIC_WS_URL pointing at localhost:8000
npm run dev
```

</details>

### Docker Compose

If you'd rather have the full stack in containers:

```bash
npm run compose:up
```

Starts `frontend` on `:3000`, `api` on `:8000`, `worker`, `postgres`, and `redis`. To tear it down:

```bash
npm run compose:down
```

---

## 🧠 How It Works

1. Create a dialog and link it to a GitHub repository.
2. Send a plain-English request — the system decides whether to answer directly or kick off a task.
3. If it needs to act, it indexes the repo and builds an execution plan.
4. Steps that touch anything risky pause and wait for your approval.
5. The worker runs shell commands, Docker actions, or GitHub API calls and streams output back through Redis and WebSocket.
6. When it's done, the middle panel shows a full trace and summary.

---

## 🚀 Tech Stack

- ✅ **Frontend:** Next.js 14, React 18, Tailwind CSS, TanStack Query
- ✅ **Backend:** FastAPI, SQLAlchemy, Pydantic
- ✅ **Background jobs:** Celery, Redis
- ✅ **LLM and retrieval:** LangChain, Chroma
- ✅ **Database:** PostgreSQL

---

## ✅ Checks

```bash
# frontend
npm run lint && npm run build

# backend
python3 -m compileall backend/app
```
