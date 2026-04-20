from types import SimpleNamespace

from backend.app.agents.runtime import AgentRuntime


class _FakeIndexer:
    def __init__(self, planner_context: dict):
        self.planner_context = planner_context

    def build_planner_context(self, db, **kwargs) -> dict:
        return self.planner_context


def _build_runtime(planner_context: dict) -> AgentRuntime:
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.llm = None
    runtime.db = object()
    runtime.indexer = _FakeIndexer(planner_context)
    return runtime


def test_build_repository_context_prefers_user_requested_conda() -> None:
    runtime = _build_runtime(
        {
            "repository_summary": "Python backend with a Next.js frontend. README recommends conda for backend setup.",
            "key_files": [
                "README.md",
                "package.json",
                "scripts/setup-conda.sh",
                "backend/environment.yml",
                "backend/requirements.txt",
                "backend/app/main.py",
            ],
            "extensions": [".py", ".ts"],
            "retrieved_context": [
                {
                    "source": "README.md",
                    "content": "Python via conda (recommended) or a plain venv.",
                }
            ],
            "critical_file_previews": [
                {
                    "source": "backend/environment.yml",
                    "content": "name: autodev-agent-backend\ndependencies:\n  - python=3.10",
                }
            ],
            "total_files": 42,
            "total_chunks": 84,
        }
    )

    repository_context = runtime.build_repository_context(
        owner="example",
        name="git-rag",
        branch="main",
        user_message="Please use the conda env and repository code to train a small model.",
    )

    assert repository_context["stack"] == "polyglot"
    assert repository_context["runtime_focus"] == "python"
    assert repository_context["environment_manager"] == "conda"
    assert repository_context["environment_reason"] == "user_requested_conda"
    assert repository_context["environment_name"] == "autodev-agent-backend"
    assert repository_context["environment_file"] == "backend/environment.yml"
    assert repository_context["install_command"] == "./scripts/setup-conda.sh"
    assert repository_context["test_command"] == "conda run -n autodev-agent-backend pytest"


def test_rule_planner_uses_detected_conda_install_command() -> None:
    runtime = _build_runtime(
        {
            "repository_summary": "Python backend. Conda is the recommended setup path.",
            "key_files": [
                "README.md",
                "scripts/setup-conda.sh",
                "backend/environment.yml",
                "backend/app/main.py",
            ],
            "extensions": [".py"],
            "retrieved_context": [],
            "critical_file_previews": [
                {
                    "source": "backend/environment.yml",
                    "content": "name: autodev-agent-backend",
                }
            ],
        }
    )
    repository_context = runtime.build_repository_context(
        owner="example",
        name="git-rag",
        branch="main",
        user_message="Use the conda environment to set up the backend.",
    )

    decision = runtime.plan_next_actions_with_rules(
        task=SimpleNamespace(steps=[]),
        user_message="Use the conda environment to set up the backend.",
        repository_context=repository_context,
    )

    assert len(decision.steps) == 1
    assert decision.steps[0].title == "Install dependencies"
    assert decision.steps[0].command == "./scripts/setup-conda.sh"
