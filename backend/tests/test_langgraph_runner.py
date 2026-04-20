from langgraph.graph import END

from backend.app.agents.graph_runner import LangGraphRunner


def _build_runner() -> LangGraphRunner:
    return LangGraphRunner.__new__(LangGraphRunner)


def _base_state(task_graph: dict) -> dict:
    return {
        "task_id": "task_1",
        "dialog_id": "dialog_1",
        "owner": "acme",
        "name": "demo",
        "branch": "main",
        "user_message": "Run training workflow",
        "repository_context": {},
        "dialog_context": [],
        "historical_execution_facts": {},
        "task_graph": task_graph,
        "results": [],
        "completion_summary": "",
        "awaiting_approval": False,
        "current_node_id": task_graph.get("active_node_id"),
        "error": None,
    }


def test_route_after_planner_resumes_pending_execution() -> None:
    runner = _build_runner()
    state = _base_state(
        {
            "status": "running",
            "active_node_id": "execute-task_1-1",
            "nodes": [
                {"id": "planner-task_1-1", "agent": "PlannerAgent", "status": "completed"},
                {
                    "id": "execute-task_1-1",
                    "agent": "ExecutionAgent",
                    "status": "pending",
                    "depends_on": ["planner-task_1-1"],
                },
            ],
        }
    )

    assert runner._route_after_planner(state) == "execution_agent"


def test_route_after_review_loops_back_to_planner_when_still_running() -> None:
    runner = _build_runner()
    state = _base_state(
        {
            "status": "running",
            "active_node_id": None,
            "nodes": [
                {"id": "planner-task_1-1", "agent": "PlannerAgent", "status": "completed"},
                {"id": "execute-task_1-1", "agent": "ExecutionAgent", "status": "completed"},
                {"id": "review-task_1-1", "agent": "ReviewAgent", "status": "completed"},
            ],
        }
    )

    assert runner._route_after_review(state) == "planner_agent"


def test_route_after_review_ends_when_graph_completed() -> None:
    runner = _build_runner()
    state = _base_state(
        {
            "status": "completed",
            "active_node_id": None,
            "nodes": [
                {"id": "planner-task_1-2", "agent": "PlannerAgent", "status": "completed"},
                {"id": "review-task_1-2", "agent": "ReviewAgent", "status": "completed"},
            ],
        }
    )

    assert runner._route_after_review(state) == END
