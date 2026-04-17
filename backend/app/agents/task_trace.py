from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def build_step_failure_message(
    *,
    position: int,
    title: str,
    command: str | None,
    output: str | None,
    error: str | None,
) -> str:
    command_line = f"Command: {command}" if command else "Command: (none)"
    error_line = f"Error: {error}" if error else "Error: (none)"
    output_preview = (output or "").strip()
    if len(output_preview) > 800:
        output_preview = output_preview[:800] + "...(truncated)"
    output_block = f"Output:\n{output_preview}" if output_preview else "Output: (empty)"
    return (
        f"[Step {position} FAILED] {title}\n"
        f"{command_line}\n"
        f"{output_block}\n"
        f"{error_line}\n\n"
        "Continuing to plan the next safe action based on this failure."
    )


def build_planned_step_payloads(
    steps: list[Any],
    *,
    iteration: int,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        payload = step.model_dump()
        payload["planning_iteration"] = iteration
        payload["act_label"] = f"Act {iteration}.{index}"
        payloads.append(payload)
    return payloads


def build_react_trace_entries(
    *,
    reasoning: str,
    steps_payload: list[dict[str, Any]],
    iteration: int,
) -> list[dict[str, Any]]:
    entries = [
        {
            "type": "thought",
            "label": f"Thought {iteration}",
            "iteration": iteration,
            "created_at": datetime.utcnow().isoformat(),
            "content_truncated": False,
            "content": reasoning,
        }
    ]
    for index, step_payload in enumerate(steps_payload, start=1):
        entries.append(
            {
                "type": "act",
                "label": step_payload.get("act_label") or f"Act {iteration}.{index}",
                "iteration": iteration,
                "step_position": None,
                "title": step_payload.get("title"),
                "kind": step_payload.get("kind"),
                "command": step_payload.get("command"),
                "created_at": datetime.utcnow().isoformat(),
                "content_truncated": False,
                "content": format_act_trace_content(step_payload),
            }
        )
    return entries


def build_observation_trace_entry(
    *,
    db_step: Any,
    status: str,
    content: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    metadata = dict(db_step.metadata_json or {})
    iteration = metadata.get("planning_iteration")
    act_label = str(metadata.get("act_label") or f"Act {iteration or '?'}")
    observation_label = act_label.replace("Act", "Obs", 1)
    output_preview = (content or "").strip()
    error_preview = (error or "").strip()
    parts: list[str] = []
    content_truncated = False
    if output_preview:
        if len(output_preview) > 1200:
            content_truncated = True
        parts.append(output_preview[:1200])
    if error_preview and error_preview not in output_preview:
        if len(error_preview) > 800:
            content_truncated = True
        parts.append(f"Error: {error_preview[:800]}")
    if not parts:
        parts.append(status)
    return {
        "type": "observation",
        "label": observation_label,
        "iteration": iteration,
        "step_position": db_step.position,
        "title": db_step.title,
        "status": status,
        "created_at": datetime.utcnow().isoformat(),
        "content_truncated": content_truncated,
        "content": "\n".join(parts),
    }


def format_act_trace_content(step_payload: dict[str, Any]) -> str:
    kind = str(step_payload.get("kind") or "shell")
    if kind in {"shell", "docker"}:
        return str(step_payload.get("command") or "")
    if kind == "github":
        parameters = step_payload.get("parameters") or {}
        action = parameters.get("action") or "github_action"
        return json.dumps({"action": action, "parameters": parameters}, ensure_ascii=True)
    return json.dumps(step_payload, ensure_ascii=True)
