from types import SimpleNamespace

from backend.app.agents.tools import GraphToolbox


class _FakeResult:
    def __init__(self, **payload) -> None:
        self._payload = payload

    def model_dump(self):
        return self._payload


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    def _execute_step(self, *, plan_step, owner, name, branch, task_id, on_output=None):
        self.calls.append(
            {
                "title": plan_step.title,
                "kind": plan_step.kind,
                "command": plan_step.command,
                "owner": owner,
                "name": name,
                "branch": branch,
                "task_id": task_id,
            }
        )
        return _FakeResult(step=plan_step.title, success=True, output="ok", metadata={"task_id": task_id})


def test_graph_toolbox_shell_tool_uses_task_scoped_execution() -> None:
    orchestrator = _FakeOrchestrator()
    toolbox = GraphToolbox(
        orchestrator,
        owner="acme",
        name="demo",
        branch="main",
        task_id="task_123",
    )

    result = toolbox.get_tool("shell.execute").invoke({"title": "Inspect repo", "command": "ls -la"})

    assert result["success"] is True
    assert orchestrator.calls[0]["kind"] == "shell"
    assert orchestrator.calls[0]["task_id"] == "task_123"

