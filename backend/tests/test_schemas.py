from backend.app.agents.types import ExecutionPlanModel, ExecutionStepModel, IntentAnalysis


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
