from types import SimpleNamespace

from backend.app.services.tasks import get_task_graph


def test_get_task_graph_returns_defaults_for_empty_plan() -> None:
    task = SimpleNamespace(plan_json={})

    task_graph = get_task_graph(task)

    assert task_graph["nodes"] == []
    assert task_graph["edges"] == []
    assert task_graph["active_node_id"] is None
    assert task_graph["worktree_path"] is None
    assert task_graph["status"] == "pending"

