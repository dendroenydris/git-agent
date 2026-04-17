from types import SimpleNamespace

from backend.app.agents.task_trace import build_observation_trace_entry, build_react_trace_entries


def test_build_react_trace_entries_include_created_at_metadata() -> None:
    entries = build_react_trace_entries(
        reasoning="Inspect the workspace before taking any risky action.",
        steps_payload=[
            {
                "title": "Inspect repository workspace",
                "kind": "shell",
                "command": "ls -la",
                "act_label": "Act 1.1",
            }
        ],
        iteration=1,
    )

    assert entries[0]["type"] == "thought"
    assert isinstance(entries[0]["created_at"], str)
    assert entries[0]["content_truncated"] is False
    assert entries[1]["type"] == "act"
    assert isinstance(entries[1]["created_at"], str)


def test_build_observation_trace_entry_marks_truncation() -> None:
    db_step = SimpleNamespace(
        position=2,
        title="Run tests",
        metadata_json={"planning_iteration": 3, "act_label": "Act 3.1"},
    )

    entry = build_observation_trace_entry(
        db_step=db_step,
        status="failed",
        content="x" * 1305,
        error="y" * 900,
    )

    assert entry["type"] == "observation"
    assert entry["label"] == "Obs 3.1"
    assert entry["step_position"] == 2
    assert entry["content_truncated"] is True
    assert isinstance(entry["created_at"], str)
