from types import SimpleNamespace

from backend.app.agents.execution_facts import (
    build_execution_facts,
    merge_execution_facts,
    should_mark_setup_complete,
    step_signature_from_record,
)
from backend.app.models.enums import StepStatus


def test_build_execution_facts_extracts_workspace_node_and_test_memory() -> None:
    task = SimpleNamespace(
        steps=[
            SimpleNamespace(
                position=1,
                status=StepStatus.COMPLETED,
                title="Inspect repository workspace",
                kind="shell",
                command="ls -la",
                output="files listed",
                error="",
            ),
            SimpleNamespace(
                position=2,
                status=StepStatus.COMPLETED,
                title="Install dependencies",
                kind="shell",
                command="npm install",
                output="installed",
                error="",
            ),
            SimpleNamespace(
                position=3,
                status=StepStatus.COMPLETED,
                title="Run test suite",
                kind="shell",
                command="pytest -q",
                output="3 passed",
                error="",
            ),
        ]
    )

    facts = build_execution_facts(task)

    assert facts["workspace_inspected"] is True
    assert facts["installed_node_dependencies"] is True
    assert facts["completed_test_commands"] == ["pytest -q"]
    assert "workspace_inspection" in facts["completed_signatures"]
    assert "npm_install_dependencies" in facts["completed_signatures"]


def test_merge_execution_facts_preserves_boolean_and_list_memory() -> None:
    merged = merge_execution_facts(
        {
            "conda_initialized": False,
            "workspace_inspected": True,
            "created_conda_envs": ["backend-env"],
            "installed_requirements": [],
            "installed_node_dependencies": False,
            "completed_test_commands": ["pytest -q"],
            "completed_signatures": ["workspace_inspection"],
        },
        {
            "conda_initialized": True,
            "workspace_inspected": False,
            "created_conda_envs": [],
            "installed_requirements": ["requirements.txt"],
            "installed_node_dependencies": True,
            "completed_test_commands": ["npm test -- --runInBand"],
            "completed_signatures": ["npm_install_dependencies"],
        },
    )

    assert merged["conda_initialized"] is True
    assert merged["workspace_inspected"] is True
    assert merged["installed_node_dependencies"] is True
    assert merged["completed_test_commands"] == ["npm test -- --runInBand", "pytest -q"]


def test_should_mark_setup_complete_accepts_node_dependency_setup() -> None:
    task = SimpleNamespace(user_message="Set up the environment and install dependencies")

    is_complete = should_mark_setup_complete(
        task,
        {
            "created_conda_envs": ["backend-env"],
            "installed_requirements": [],
            "installed_node_dependencies": True,
        },
    )

    assert is_complete is True


def test_step_signature_from_record_covers_test_and_install_commands() -> None:
    assert step_signature_from_record("Inspect repository workspace", "shell", "pwd") == "workspace_inspection"
    assert step_signature_from_record("Install dependencies", "shell", "pnpm install") == "pnpm_install_dependencies"
    assert step_signature_from_record("Run tests", "shell", "pytest -q") == "test_command:pytest -q"
