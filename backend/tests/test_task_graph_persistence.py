from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.models.entities import TaskRun
from backend.app.models.enums import ApprovalStatus, TaskStatus
from backend.app.services.tasks import (
    get_task_graph,
    initialize_task_graph,
    set_task_graph_active_node,
    task_to_read,
    update_task_graph_node,
)


def test_task_graph_helpers_persist_nodes_and_api_shape() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    task = TaskRun(
        dialog_id="dialog_test",
        repository_id=None,
        user_message="Run checks",
        status=TaskStatus.QUEUED,
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    initialize_task_graph(
        db,
        task,
        nodes=[
            {
                "id": "node_plan",
                "agent": "PlannerAgent",
                "title": "Plan graph workflow",
                "status": "completed",
                "depends_on": [],
            },
            {
                "id": "node_exec",
                "agent": "ExecutionAgent",
                "title": "Run checks",
                "status": "pending",
                "depends_on": ["node_plan"],
            },
        ],
        active_node_id="node_exec",
        worktree_path="/tmp/worktrees/task_1",
        base_repo_path="/tmp/repositories/acme__demo",
        status="running",
    )
    update_task_graph_node(db, task, node_id="node_exec", status="completed", result_summary="Checks passed")
    set_task_graph_active_node(db, task, node_id=None)
    db.commit()
    db.refresh(task)

    graph = get_task_graph(task)
    payload = task_to_read(task).model_dump(mode="json")

    assert graph["worktree_path"] == "/tmp/worktrees/task_1"
    assert graph["nodes"][1]["status"] == "completed"
    assert payload["plan_json"]["task_graph"]["nodes"][1]["result_summary"] == "Checks passed"
    assert payload["plan_json"]["task_graph"]["active_node_id"] is None

