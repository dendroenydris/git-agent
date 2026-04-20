from __future__ import annotations

from typing import Any


TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "shell.execute",
        "server": "builtin",
        "description": "Run an allowlisted shell command in the repository workspace",
        "parameters": {"command": "string"},
        "mock": False,
    },
    {
        "name": "docker.run",
        "server": "builtin",
        "description": "Run a containerized command for verification",
        "parameters": {"image": "string", "command": "string"},
        "mock": False,
    },
    {
        "name": "github.create_issue_comment",
        "server": "builtin",
        "description": "Create an issue or PR comment using a PAT",
        "parameters": {"issue_number": "int", "body": "string"},
        "mock": False,
    },
    {
        "name": "github.dispatch_workflow",
        "server": "builtin",
        "description": "Trigger a GitHub Actions workflow dispatch",
        "parameters": {"workflow_id": "string"},
        "mock": False,
    },
]


def list_tool_catalog() -> list[dict[str, Any]]:
    return [dict(tool) for tool in TOOL_CATALOG]


def list_api_tools() -> dict[str, list[dict[str, str]]]:
    return {
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
            }
            for tool in TOOL_CATALOG
        ]
    }
