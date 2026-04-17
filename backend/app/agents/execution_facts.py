from __future__ import annotations

import re
from typing import Any

from backend.app.models.enums import StepStatus


def build_historical_execution_facts(dialog: Any, *, current_task_id: str) -> dict[str, Any]:
    aggregated_facts: dict[str, Any] = {
        "conda_initialized": False,
        "workspace_inspected": False,
        "created_conda_envs": [],
        "installed_requirements": [],
        "installed_node_dependencies": False,
        "completed_test_commands": [],
        "completed_signatures": [],
        "recent_task_summaries": [],
    }

    created_envs: set[str] = set()
    installed_requirements: set[str] = set()
    completed_test_commands: set[str] = set()
    completed_signatures: set[str] = set()
    recent_task_summaries: list[str] = []

    for historical_task in sorted(dialog.tasks, key=lambda item: item.created_at):
        if historical_task.id == current_task_id:
            continue

        task_facts = build_execution_facts(historical_task)
        aggregated_facts["conda_initialized"] = (
            aggregated_facts["conda_initialized"] or task_facts["conda_initialized"]
        )
        aggregated_facts["workspace_inspected"] = (
            aggregated_facts["workspace_inspected"] or task_facts["workspace_inspected"]
        )
        aggregated_facts["installed_node_dependencies"] = (
            aggregated_facts["installed_node_dependencies"] or task_facts["installed_node_dependencies"]
        )
        created_envs.update(task_facts["created_conda_envs"])
        installed_requirements.update(task_facts["installed_requirements"])
        completed_test_commands.update(task_facts["completed_test_commands"])
        completed_signatures.update(task_facts["completed_signatures"])

        if historical_task.summary:
            recent_task_summaries.append(f"- task {historical_task.id}: {historical_task.summary[:240]}")

    aggregated_facts["created_conda_envs"] = sorted(created_envs)
    aggregated_facts["installed_requirements"] = sorted(installed_requirements)
    aggregated_facts["completed_test_commands"] = sorted(completed_test_commands)
    aggregated_facts["completed_signatures"] = sorted(completed_signatures)
    aggregated_facts["recent_task_summaries"] = recent_task_summaries[-5:]
    return aggregated_facts


def format_historical_execution_facts_section(facts: dict[str, Any]) -> str:
    lines = [
        f"- conda_initialized: {facts.get('conda_initialized', False)}",
        f"- workspace_inspected: {facts.get('workspace_inspected', False)}",
        f"- created_conda_envs: {', '.join(facts.get('created_conda_envs', [])) or 'none'}",
        f"- installed_requirements: {', '.join(facts.get('installed_requirements', [])) or 'none'}",
        f"- installed_node_dependencies: {facts.get('installed_node_dependencies', False)}",
        f"- completed_test_commands: {', '.join(facts.get('completed_test_commands', [])[:6]) or 'none'}",
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
        "workspace_inspected": bool(
            primary_facts.get("workspace_inspected") or historical_facts.get("workspace_inspected")
        ),
        "created_conda_envs": sorted(
            set(primary_facts.get("created_conda_envs", [])) | set(historical_facts.get("created_conda_envs", []))
        ),
        "installed_requirements": sorted(
            set(primary_facts.get("installed_requirements", [])) | set(historical_facts.get("installed_requirements", []))
        ),
        "installed_node_dependencies": bool(
            primary_facts.get("installed_node_dependencies") or historical_facts.get("installed_node_dependencies")
        ),
        "completed_test_commands": sorted(
            set(primary_facts.get("completed_test_commands", [])) | set(historical_facts.get("completed_test_commands", []))
        ),
        "completed_signatures": sorted(
            set(primary_facts.get("completed_signatures", [])) | set(historical_facts.get("completed_signatures", []))
        ),
    }


def build_execution_facts(task: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "conda_initialized": False,
        "workspace_inspected": False,
        "created_conda_envs": [],
        "installed_requirements": [],
        "installed_node_dependencies": False,
        "completed_test_commands": [],
        "completed_signatures": [],
    }

    created_envs: set[str] = set()
    installed_requirements: set[str] = set()
    completed_test_commands: set[str] = set()
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

        if _is_workspace_inspection_command(lowered_command):
            facts["workspace_inspected"] = True

        if _is_node_install_command(lowered_command):
            facts["installed_node_dependencies"] = True

        if _is_test_command(lowered_command):
            completed_test_commands.add(command)

    facts["workspace_inspected"] = bool(facts["workspace_inspected"])
    facts["created_conda_envs"] = sorted(created_envs)
    facts["installed_requirements"] = sorted(installed_requirements)
    facts["completed_test_commands"] = sorted(completed_test_commands)
    facts["completed_signatures"] = sorted(completed_signatures)
    return facts


def format_execution_facts_section(task: Any) -> str:
    facts = build_execution_facts(task)
    lines = [
        f"- conda_initialized: {facts['conda_initialized']}",
        f"- workspace_inspected: {facts['workspace_inspected']}",
        f"- created_conda_envs: {', '.join(facts['created_conda_envs']) or 'none'}",
        f"- installed_requirements: {', '.join(facts['installed_requirements']) or 'none'}",
        f"- installed_node_dependencies: {facts['installed_node_dependencies']}",
    ]
    test_commands = facts.get("completed_test_commands", [])
    if test_commands:
        lines.append(f"- completed_test_commands: {', '.join(test_commands[:4])}")
    else:
        lines.append("- completed_test_commands: none")
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
        if _is_workspace_inspection_command(lowered_command) or "inspect repository workspace" in lowered_title:
            return "workspace_inspection"

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

        if _is_node_install_command(lowered_command):
            package_manager = lowered_command.split(maxsplit=1)[0]
            return f"{package_manager}_install_dependencies"

        if _is_test_command(lowered_command):
            return f"test_command:{lowered_command}"

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
    has_python_requirements = bool(execution_facts.get("installed_requirements"))
    has_node_dependencies = bool(execution_facts.get("installed_node_dependencies"))
    return has_env and (has_python_requirements or has_node_dependencies)


def _is_workspace_inspection_command(lowered_command: str) -> bool:
    inspection_patterns = (
        "ls",
        "ls -",
        "pwd",
        "git status",
        "rg --files",
    )
    return any(lowered_command == pattern or lowered_command.startswith(f"{pattern} ") for pattern in inspection_patterns)


def _is_node_install_command(lowered_command: str) -> bool:
    node_install_commands = (
        "npm install",
        "pnpm install",
        "yarn install",
    )
    return any(lowered_command == command or lowered_command.startswith(f"{command} ") for command in node_install_commands)


def _is_test_command(lowered_command: str) -> bool:
    test_commands = (
        "pytest",
        "npm test",
        "pnpm test",
        "yarn test",
    )
    return any(lowered_command == command or lowered_command.startswith(f"{command} ") for command in test_commands)
