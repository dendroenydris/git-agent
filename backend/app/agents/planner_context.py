from __future__ import annotations

import json
import re
from typing import Any

DIALOG_CONTEXT_MESSAGE_LIMIT = 10
DIALOG_CONTEXT_CHAR_LIMIT = 300
EXECUTION_HISTORY_STEP_LIMIT = 10
EXECUTION_HISTORY_OUTPUT_CHAR_LIMIT = 500
KEY_FILES_LIMIT = 25
RETRIEVED_CONTEXT_LIMIT = 6
RETRIEVED_CONTEXT_CHAR_LIMIT = 900
REACT_TRACE_LIMIT = 18
REACT_THOUGHT_CHAR_LIMIT = 400
REACT_ACTION_CHAR_LIMIT = 300
REACT_OBSERVATION_CHAR_LIMIT = 600
CRITICAL_PREVIEW_LIMIT = 6
CRITICAL_PREVIEW_CHAR_LIMIT = 800


def _truncate_text(value: Any, *, limit: int) -> tuple[str, bool]:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text, False
    return text[:limit] + "...(truncated)", True


def build_dialog_context(messages: list[Any]) -> list[str]:
    if not messages:
        return []

    ordered_messages = sorted(messages, key=lambda item: item.created_at)
    snippets: list[str] = []
    for message in ordered_messages[-DIALOG_CONTEXT_MESSAGE_LIMIT:]:
        role = getattr(message.type, "value", str(message.type))
        content, was_truncated = _truncate_text(
            (message.content or "").replace("\n", " "),
            limit=DIALOG_CONTEXT_CHAR_LIMIT,
        )
        suffix = " [truncated]" if was_truncated else ""
        snippets.append(f"{role}: {content}{suffix}")
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
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = []

    # The ReAct loop executes one action per planning turn, so keep only
    # the first executable step even if the model emits a longer plan.
    payload["steps"] = [] if payload["is_complete"] else raw_steps[:1]
    return payload


def build_execution_history(task: Any) -> str:
    if not task.steps:
        return "No prior execution history."

    history_lines: list[str] = []
    steps = sorted(task.steps, key=lambda item: item.position)
    selected_steps = steps[-EXECUTION_HISTORY_STEP_LIMIT:]
    if len(steps) > len(selected_steps):
        history_lines.append(
            f"Showing {len(selected_steps)} of {len(steps)} executed steps from recent history."
        )
    for step in selected_steps:
        history_lines.append(f"[{step.position}] {step.title} :: {step.status}")
        if step.command:
            history_lines.append(f"command: {step.command}")
        if step.output:
            output, was_truncated = _truncate_text(step.output, limit=EXECUTION_HISTORY_OUTPUT_CHAR_LIMIT)
            history_lines.append(f"output: {output}")
            if was_truncated:
                history_lines.append("output_note: truncated for planner context budget")
        if step.error:
            error, was_truncated = _truncate_text(step.error, limit=EXECUTION_HISTORY_OUTPUT_CHAR_LIMIT)
            history_lines.append(f"error: {error}")
            if was_truncated:
                history_lines.append("error_note: truncated for planner context budget")
    return "\n".join(history_lines)


def build_key_files_section(repository_context: dict[str, Any]) -> str:
    key_files = repository_context.get("key_files", [])
    if not isinstance(key_files, list) or not key_files:
        return "No indexed key files."
    selected_files = key_files[:KEY_FILES_LIMIT]
    header = (
        f"Showing {len(selected_files)} of {len(key_files)} indexed key files."
        if len(key_files) > len(selected_files)
        else f"Showing all {len(selected_files)} indexed key files."
    )
    return "\n".join([header, *[f"- {path}" for path in selected_files]])


def build_retrieved_context_section(repository_context: dict[str, Any]) -> str:
    retrieved_context = repository_context.get("retrieved_context", [])
    if not isinstance(retrieved_context, list) or not retrieved_context:
        return "No retrieved chunks for this request."

    lines: list[str] = []
    selected_items = retrieved_context[:RETRIEVED_CONTEXT_LIMIT]
    lines.append(
        f"Showing {len(selected_items)} of {len(retrieved_context)} retrieved chunks."
        if len(retrieved_context) > len(selected_items)
        else f"Showing all {len(selected_items)} retrieved chunks."
    )
    for item in selected_items:
        if not isinstance(item, dict):
            continue
        source = item.get("source", "unknown")
        content, was_truncated = _truncate_text(item.get("content", ""), limit=RETRIEVED_CONTEXT_CHAR_LIMIT)
        truncation_note = "\n[chunk truncated]" if was_truncated else ""
        lines.append(f"[{source}]\n{content}{truncation_note}")
    return "\n\n---\n\n".join(lines) if lines else "No retrieved chunks for this request."


def build_react_trace_context(task: Any) -> str:
    """Return a formatted Thought / Action / Observation history for the ReAct prompt."""
    react_trace: list[dict[str, Any]] = (task.plan_json or {}).get("react_trace", [])
    if not react_trace:
        return "No prior ReAct trace — this is the first Thought."

    lines: list[str] = []
    selected_entries = react_trace[-REACT_TRACE_LIMIT:]
    if len(react_trace) > len(selected_entries):
        lines.append(
            f"Showing {len(selected_entries)} of {len(react_trace)} ReAct trace entries."
        )
    for entry in selected_entries:
        entry_type = entry.get("type", "")
        label = entry.get("label", "?")
        content = (entry.get("content") or "").strip()
        if entry_type == "thought":
            thought, was_truncated = _truncate_text(content, limit=REACT_THOUGHT_CHAR_LIMIT)
            lines.append(f"Thought [{label}]: {thought}")
            if was_truncated:
                lines.append("thought_note: truncated for planner context budget")
        elif entry_type == "act":
            title = entry.get("title", "")
            kind = entry.get("kind", "")
            action, was_truncated = _truncate_text(content, limit=REACT_ACTION_CHAR_LIMIT)
            lines.append(f"Action  [{label}]: {title} ({kind}) → {action}")
            if was_truncated:
                lines.append("action_note: truncated for planner context budget")
        elif entry_type == "observation":
            status = entry.get("status", "")
            observation, was_truncated = _truncate_text(content, limit=REACT_OBSERVATION_CHAR_LIMIT)
            lines.append(f"Obs     [{label}] ({status}): {observation}")
            if was_truncated:
                lines.append("observation_note: truncated for planner context budget")
    return "\n".join(lines) if lines else "No prior ReAct trace."


def build_critical_previews_section(repository_context: dict[str, Any]) -> str:
    previews = repository_context.get("critical_file_previews", [])
    if not isinstance(previews, list) or not previews:
        return "No critical file previews available."

    lines: list[str] = []
    selected_previews = previews[:CRITICAL_PREVIEW_LIMIT]
    lines.append(
        f"Showing {len(selected_previews)} of {len(previews)} critical file previews."
        if len(previews) > len(selected_previews)
        else f"Showing all {len(selected_previews)} critical file previews."
    )
    for preview in selected_previews:
        if not isinstance(preview, dict):
            continue
        source = preview.get("source", "unknown")
        content, was_truncated = _truncate_text(preview.get("content", ""), limit=CRITICAL_PREVIEW_CHAR_LIMIT)
        truncation_note = "\n[file preview truncated]" if was_truncated else ""
        lines.append(f"[{source}]\n{content}{truncation_note}")
    return "\n\n---\n\n".join(lines) if lines else "No critical file previews available."


def build_context_budget_section(
    *,
    dialog_context: list[str],
    repository_context: dict[str, Any],
    task: Any,
) -> str:
    react_trace = (task.plan_json or {}).get("react_trace", [])
    key_files = repository_context.get("key_files", [])
    retrieved_context = repository_context.get("retrieved_context", [])
    previews = repository_context.get("critical_file_previews", [])
    repository_summary = str(repository_context.get("repository_summary") or "").strip()
    lines = [
        "Context layers available to this planning turn:",
        (
            f"- dialog_context: {min(len(dialog_context), DIALOG_CONTEXT_MESSAGE_LIMIT)} shown "
            f"(recent messages, each clipped to {DIALOG_CONTEXT_CHAR_LIMIT} chars)"
        ),
        (
            f"- react_trace: {min(len(react_trace), REACT_TRACE_LIMIT)} shown "
            f"(Thought/Act/Observation history)"
        ),
        (
            f"- repository_summary: {'present' if repository_summary else 'missing'}"
        ),
        (
            f"- key_files: {min(len(key_files), KEY_FILES_LIMIT)} shown out of {len(key_files)} indexed files"
        ),
        (
            f"- retrieved_context: {min(len(retrieved_context), RETRIEVED_CONTEXT_LIMIT)} semantic chunks "
            f"shown out of {len(retrieved_context)} retrieved"
        ),
        (
            f"- critical_file_previews: {min(len(previews), CRITICAL_PREVIEW_LIMIT)} previews "
            f"shown out of {len(previews)} selected files"
        ),
        (
            f"- repository_index: total_files={repository_context.get('total_files', 0)}, "
            f"total_chunks={repository_context.get('total_chunks', 0)}"
        ),
        "Use the latest observation and execution facts first; use retrieved chunks and critical previews to ground file-specific actions.",
    ]
    return "\n".join(lines)
