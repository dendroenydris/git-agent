from __future__ import annotations

import re
from typing import Any

from backend.app.models.enums import StepStatus


def build_historical_execution_facts(dialog: Any, *, current_task_id: str) -> dict[str, Any]:
    aggregated_facts: dict[str, Any] = {
        "conda_initialized": False,
        "created_conda_envs": [],
        "installed_requirements": [],
        "completed_signatures": [],
        "recent_task_summaries": [],
    }

    created_envs: set[str] = set()
    installed_requirements: set[str] = set()
    completed_signatures: set[str] = set()
    recent_task_summaries: list[str] = []

    for historical_task in sorted(dialog.tasks, key=lambda item: item.created_at):
        if historical_task.id == current_task_id:
            continue

        task_facts = build_execution_facts(historical_task)
        aggregated_facts["conda_initialized"] = (
            aggregated_facts["conda_initialized"] or task_facts["conda_initialized"]
        )
        created_envs.update(task_facts["created_conda_envs"])
        installed_requirements.update(task_facts["installed_requirements"])
        completed_signatures.update(task_facts["completed_signatures"])

        if historical_task.summary:
            recent_task_summaries.append(f"- task {historical_task.id}: {historical_task.summary[:240]}")

    aggregated_facts["created_conda_envs"] = sorted(created_envs)
    aggregated_facts["installed_requirements"] = sorted(installed_requirements)
    aggregated_facts["completed_signatures"] = sorted(completed_signatures)
    aggregated_facts["recent_task_summaries"] = recent_task_summaries[-5:]
    return aggregated_facts


def format_historical_execution_facts_section(facts: dict[str, Any]) -> str:
    lines = [
        f"- conda_initialized: {facts.get('conda_initialized', False)}",
        f"- created_conda_envs: {', '.join(facts.get('created_conda_envs', [])) or 'none'}",
        f"- installed_requirements: {', '.join(facts.get('installed_requirements', [])) or 'none'}",
        f"- completed_signatures: {', '.join(facts.get('completed_signatures', [])[:8]) or 'none'}",
    ]
    summaries = facts.get("recent_task_summaries", [])
    if summaries:
        lines.append("Recent task summaries:")
        lines.extend(str(summary) for summary in summaries)
    return "\n".join(lines)


def latest_replan_failure_message(task: Any) -> str:
    replan_requests = (task.plan_json or {}).get("replan_requests", [])
    if not isinstance(replan_requests, list) or not replan_requests:
        return "None."
    latest_request = replan_requests[-1]
    if not isinstance(latest_request, dict):
        return "None."
    message = latest_request.get("failure_message")
    return str(message) if message else "None."


def merge_execution_facts(primary_facts: dict[str, Any], historical_facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "conda_initialized": bool(primary_facts.get("conda_initialized") or historical_facts.get("conda_initialized")),
        "created_conda_envs": sorted(
            set(primary_facts.get("created_conda_envs", [])) | set(historical_facts.get("created_conda_envs", []))
        ),
        "installed_requirements": sorted(
            set(primary_facts.get("installed_requirements", [])) | set(historical_facts.get("installed_requirements", []))
        ),
        "completed_signatures": sorted(
            set(primary_facts.get("completed_signatures", [])) | set(historical_facts.get("completed_signatures", []))
        ),
    }


def build_execution_facts(task: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "conda_initialized": False,
        "created_conda_envs": [],
        "installed_requirements": [],
        "completed_signatures": [],
    }

    created_envs: set[str] = set()
    installed_requirements: set[str] = set()
    completed_signatures: set[str] = set()

    for step in sorted(task.steps, key=lambda item: item.position):
        if step.status != StepStatus.COMPLETED:
            continue

        signature = step_signature_from_record(step.title, step.kind, step.command)
        if signature:
            completed_signatures.add(signature)

        command = (step.command or "").strip()
        output = ((step.output or "") + "\n" + (step.error or "")).lower()
        lowered_command = command.lower()

        if "conda init" in lowered_command and (
            "no change" in output or "modified" in output or "initialized" in output
        ):
            facts["conda_initialized"] = True

        env_match = re.search(r"conda\s+create(?:[^\n])*?(?:-n|--name)\s+([A-Za-z0-9_.-]+)", command)
        if env_match:
            created_envs.add(env_match.group(1))

        requirements_match = re.search(r"(?:pip|pip3)\s+install\s+-r\s+([^\s&;]+)", command)
        if requirements_match:
            installed_requirements.add(requirements_match.group(1))

    facts["created_conda_envs"] = sorted(created_envs)
    facts["installed_requirements"] = sorted(installed_requirements)
    facts["completed_signatures"] = sorted(completed_signatures)
    return facts


def format_execution_facts_section(task: Any) -> str:
    facts = build_execution_facts(task)
    lines = [
        f"- conda_initialized: {facts['conda_initialized']}",
        f"- created_conda_envs: {', '.join(facts['created_conda_envs']) or 'none'}",
        f"- installed_requirements: {', '.join(facts['installed_requirements']) or 'none'}",
    ]
    signatures = facts.get("completed_signatures", [])
    if signatures:
        lines.append(f"- completed_signatures: {', '.join(signatures[:8])}")
    else:
        lines.append("- completed_signatures: none")
    return "\n".join(lines)


def is_redundant_completed_step(step: Any, completed_signatures: set[str]) -> bool:
    signature = step_signature_from_record(step.title, step.kind, step.command)
    return bool(signature and signature in completed_signatures)


def step_signature_from_record(title: str, kind: str, command: str | None) -> str | None:
    lowered_title = (title or "").lower()
    lowered_command = (command or "").strip().lower()

    if kind == "shell":
        if "conda init" in lowered_command or "initialize conda" in lowered_title:
            shell_name = "generic"
            shell_match = re.search(r"conda\s+init\s+([a-z0-9_.-]+)", lowered_command)
            if shell_match:
                shell_name = shell_match.group(1)
            return f"conda_init:{shell_name}"

        env_match = re.search(r"conda\s+create(?:[^\n])*?(?:-n|--name)\s+([a-z0-9_.-]+)", lowered_command)
        if env_match:
            return f"conda_create_env:{env_match.group(1)}"

        requirements_match = re.search(r"(?:pip|pip3)\s+install\s+-r\s+([^\s&;]+)", lowered_command)
        if requirements_match:
            env_name = "unknown"
            activate_match = re.search(r"conda\s+activate\s+([a-z0-9_.-]+)", lowered_command)
            if activate_match:
                env_name = activate_match.group(1)
            return f"pip_install_requirements:{env_name}:{requirements_match.group(1)}"

    return None


def should_mark_setup_complete(task: Any, execution_facts: dict[str, Any]) -> bool:
    lowered_request = (task.user_message or "").lower()
    is_setup_request = any(
        token in lowered_request
        for token in ["conda", "environment", "env", "requirements.txt", "install dependencies", "setup"]
    )
    if not is_setup_request:
        return False

    has_env = bool(execution_facts.get("created_conda_envs"))
    has_requirements = bool(execution_facts.get("installed_requirements"))
    return has_env and has_requirements
