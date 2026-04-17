from datetime import datetime, timedelta
from types import SimpleNamespace

from backend.app.agents.planner_context import (
    build_context_budget_section,
    build_dialog_context,
    build_retrieved_context_section,
)


def test_build_dialog_context_marks_truncated_messages() -> None:
    messages = [
        SimpleNamespace(
            created_at=datetime.utcnow(),
            type=SimpleNamespace(value="user"),
            content="x" * 350,
        )
    ]

    dialog_context = build_dialog_context(messages)

    assert len(dialog_context) == 1
    assert "[truncated]" in dialog_context[0]


def test_build_retrieved_context_section_includes_budget_header() -> None:
    repository_context = {
        "retrieved_context": [
            {"source": f"src/file_{index}.py", "content": "x" * 950}
            for index in range(7)
        ]
    }

    section = build_retrieved_context_section(repository_context)

    assert "Showing 6 of 7 retrieved chunks." in section
    assert "[chunk truncated]" in section


def test_build_context_budget_section_summarizes_layers() -> None:
    now = datetime.utcnow()
    dialog_context = [
        f"user: message {index}"
        for index in range(8)
    ]
    task = SimpleNamespace(
        plan_json={
            "react_trace": [
                {
                    "type": "observation",
                    "label": f"Obs {index}",
                    "content": "done",
                    "created_at": (now + timedelta(seconds=index)).isoformat(),
                }
                for index in range(20)
            ]
        }
    )
    repository_context = {
        "repository_summary": "Python service with Redis worker.",
        "key_files": [f"backend/file_{index}.py" for index in range(30)],
        "retrieved_context": [{"source": "backend/app/main.py", "content": "..." } for _ in range(4)],
        "critical_file_previews": [{"source": "backend/app/main.py", "content": "..."} for _ in range(2)],
        "total_files": 120,
        "total_chunks": 480,
    }

    section = build_context_budget_section(
        dialog_context=dialog_context,
        repository_context=repository_context,
        task=task,
    )

    assert "dialog_context: 8 shown" in section
    assert "react_trace: 18 shown" in section
    assert "repository_summary: present" in section
    assert "key_files: 25 shown out of 30 indexed files" in section
    assert "total_files=120, total_chunks=480" in section
