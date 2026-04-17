from backend.app.agents.types import ExecutionPlanModel, ExecutionStepModel, IntentAnalysis
from backend.app.agents.planner_context import sanitize_decision_payload


def test_execution_plan_model_serializes_typed_steps() -> None:
    plan = ExecutionPlanModel(
        intent=IntentAnalysis(
            objective="Run tests",
            category="testing",
            complexity="medium",
            needs_repository_context=True,
        ),
        repository_context={"install_command": "pip install -r requirements.txt"},
        steps=[
            ExecutionStepModel(
                title="Inspect repository workspace",
                kind="shell",
                command="ls -la",
                requires_approval=True,
            ),
            ExecutionStepModel(
                title="Run test suite",
                kind="shell",
                command="pytest",
                requires_approval=True,
            ),
        ],
    )

    payload = plan.model_dump()

    assert payload["intent"]["category"] == "testing"
    assert payload["steps"][1]["command"] == "pytest"
    assert payload["steps"][1]["requires_approval"] is True


def test_sanitize_decision_payload_keeps_only_first_step() -> None:
    payload = sanitize_decision_payload(
        {
            "intent": {"category": "automation"},
            "reasoning": "Inspect first, then test.",
            "is_complete": False,
            "steps": [
                {"title": "Inspect repository workspace", "kind": "shell", "command": "ls -la"},
                {"title": "Run tests", "kind": "shell", "command": "pytest"},
            ],
        },
        user_message="Inspect the repo and run tests",
    )

    assert len(payload["steps"]) == 1
    assert payload["steps"][0]["command"] == "ls -la"


def test_sanitize_decision_payload_clears_steps_when_complete() -> None:
    payload = sanitize_decision_payload(
        {
            "intent": {"category": "automation"},
            "reasoning": "The task is already complete.",
            "is_complete": True,
            "steps": [
                {"title": "Run tests", "kind": "shell", "command": "pytest"},
            ],
        },
        user_message="Run tests",
    )

    assert payload["steps"] == []
