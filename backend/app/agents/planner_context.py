from __future__ import annotations

import json
import re
from typing import Any


def build_dialog_context(messages: list[Any]) -> list[str]:
    if not messages:
        return []

    ordered_messages = sorted(messages, key=lambda item: item.created_at)
    snippets: list[str] = []
    for message in ordered_messages[-10:]:
        role = getattr(message.type, "value", str(message.type))
        content = (message.content or "").strip().replace("\n", " ")
        snippets.append(f"{role}: {content[:300]}")
    return snippets


def parse_json_payload(raw_content: str) -> dict[str, Any]:
    candidate = raw_content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
        candidate = re.sub(r"```$", "", candidate).strip()
    return json.loads(candidate)


def sanitize_decision_payload(payload: dict[str, Any], *, user_message: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    intent = payload.get("intent") or {}
    if not isinstance(intent, dict):
        intent = {}
    complexity = str(intent.get("complexity", "medium")).lower()
    if complexity not in {"low", "medium", "high"}:
        complexity = "medium"
    intent["complexity"] = complexity
    intent["objective"] = intent.get("objective") or user_message
    intent["category"] = intent.get("category") or "automation"
    intent["needs_repository_context"] = bool(intent.get("needs_repository_context", True))
    payload["intent"] = intent
    payload["reasoning"] = str(payload.get("reasoning") or "Planner generated the next executable steps.")
    payload["is_complete"] = bool(payload.get("is_complete", False))
    payload["completion_summary"] = payload.get("completion_summary")
    payload["steps"] = payload.get("steps") or []
    return payload


def build_execution_history(task: Any) -> str:
    if not task.steps:
        return "No prior execution history."

    history_lines: list[str] = []
    for step in sorted(task.steps, key=lambda item: item.position)[-10:]:
        history_lines.append(f"[{step.position}] {step.title} :: {step.status}")
        if step.command:
            history_lines.append(f"command: {step.command}")
        if step.output:
            history_lines.append(f"output: {step.output[:500]}")
        if step.error:
            history_lines.append(f"error: {step.error[:500]}")
    return "\n".join(history_lines)


def build_key_files_section(repository_context: dict[str, Any]) -> str:
    key_files = repository_context.get("key_files", [])
    if not isinstance(key_files, list) or not key_files:
        return "No indexed key files."
    return "\n".join(f"- {path}" for path in key_files[:25])


def build_retrieved_context_section(repository_context: dict[str, Any]) -> str:
    retrieved_context = repository_context.get("retrieved_context", [])
    if not isinstance(retrieved_context, list) or not retrieved_context:
        return "No retrieved chunks for this request."

    lines: list[str] = []
    for item in retrieved_context[:6]:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "unknown")
        content = str(item.get("content", ""))[:900]
        lines.append(f"[{source}]\n{content}")
    return "\n\n---\n\n".join(lines) if lines else "No retrieved chunks for this request."


def build_critical_previews_section(repository_context: dict[str, Any]) -> str:
    previews = repository_context.get("critical_file_previews", [])
    if not isinstance(previews, list) or not previews:
        return "No critical file previews available."

    lines: list[str] = []
    for preview in previews[:6]:
        if not isinstance(preview, dict):
            continue
        source = preview.get("source", "unknown")
        content = str(preview.get("content", ""))[:800]
        lines.append(f"[{source}]\n{content}")
    return "\n\n---\n\n".join(lines) if lines else "No critical file previews available."
