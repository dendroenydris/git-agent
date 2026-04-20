from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.agents.execution_facts import (
    build_execution_facts,
    format_execution_facts_section,
    format_historical_execution_facts_section,
    is_redundant_completed_step,
    latest_replan_failure_message,
    merge_execution_facts,
    should_mark_setup_complete,
)
from backend.app.agents.planner_context import (
    build_context_budget_section,
    build_critical_previews_section,
    build_execution_history,
    build_key_files_section,
    build_react_trace_context,
    build_retrieved_context_section,
    parse_json_payload,
    sanitize_decision_payload,
)
from backend.app.agents.types import ExecutionStepModel, PlannerDecisionModel, ToolResult
from backend.app.core.config import get_settings
from backend.app.executors.local import LocalExecutor
from backend.app.models.enums import ApprovalMode
from backend.app.rag.indexer import RepositoryIndexer
from backend.app.services.app_settings import get_or_create_app_settings
from backend.app.services.github_service import GitHubContext, GitHubService
from backend.app.services.worktree_manager import WorktreeManager


logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.indexer = RepositoryIndexer()
        self.executor = LocalExecutor()
        self.github_service = GitHubService()
        self.worktree_manager = WorktreeManager()
        self.llm = (
            ChatOpenAI(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                temperature=0.1,
            )
            if self.settings.has_usable_openai_api_key
            else None
        )

    def build_repository_context(
        self,
        *,
        owner: str,
        name: str,
        branch: str,
        user_message: str,
    ) -> dict[str, Any]:
        base_context = self.indexer.build_planner_context(
            self.db,
            owner=owner,
            name=name,
            branch=branch,
            query=user_message,
        )
        key_files = list(base_context.get("key_files", []))
        extensions = set(base_context.get("extensions", []))
        lower_paths = [str(source).lower() for source in key_files]
        filenames = {Path(source).name for source in key_files}
        lower_filenames = {filename.lower() for filename in filenames}
        context_text = self._build_repository_signal_text(base_context)
        is_node = "package.json" in lower_filenames
        is_python = bool(
            {"requirements.txt", "environment.yml", "environment.yaml", "pyproject.toml", "pipfile"} & lower_filenames
        ) or ".py" in extensions
        stack = "polyglot" if is_node and is_python else "node" if is_node else "python" if is_python else "generic"
        environment_strategy = self._detect_environment_strategy(
            user_message=user_message,
            lower_paths=lower_paths,
            lower_filenames=lower_filenames,
            context_text=context_text,
            stack=stack,
        )
        return {
            "repository_summary": base_context.get("repository_summary", ""),
            "install_command": environment_strategy["install_command"],
            "test_command": environment_strategy["test_command"],
            "stack": stack,
            "runtime_focus": environment_strategy["runtime_focus"],
            "environment_manager": environment_strategy["environment_manager"],
            "environment_reason": environment_strategy["environment_reason"],
            "environment_name": environment_strategy["environment_name"],
            "environment_file": environment_strategy["environment_file"],
            "key_files": sorted(key_files)[:40],
            "extensions": sorted(extensions)[:20],
            "retrieved_context": base_context.get("retrieved_context", []),
            "critical_file_previews": base_context.get("critical_file_previews", []),
            "total_files": base_context.get("total_files", 0),
            "total_chunks": base_context.get("total_chunks", 0),
        }

    def plan_next_actions(
        self,
        *,
        task,
        user_message: str,
        dialog_context: list[str],
        repository_context: dict[str, Any],
        historical_execution_facts: dict[str, Any] | None = None,
    ) -> PlannerDecisionModel:
        historical_facts = historical_execution_facts or {}
        decision = self.plan_next_actions_with_llm(
            task=task,
            user_message=user_message,
            dialog_context=dialog_context,
            repository_context=repository_context,
            historical_execution_facts=historical_facts,
        )
        if decision is None:
            decision = self.plan_next_actions_with_rules(
                task=task,
                user_message=user_message,
                repository_context=repository_context,
            )
        return self.normalize_decision(
            decision=decision,
            task=task,
            historical_execution_facts=historical_facts,
        )

    def plan_next_actions_with_llm(
        self,
        *,
        task,
        user_message: str,
        dialog_context: list[str],
        repository_context: dict[str, Any],
        historical_execution_facts: dict[str, Any] | None = None,
    ) -> PlannerDecisionModel | None:
        if self.llm is None:
            return None

        historical_facts = historical_execution_facts or {}
        context_preview = "\n".join(dialog_context[-8:]) if dialog_context else "No prior dialog context."
        react_trace = build_react_trace_context(task)
        execution_history = build_execution_history(task)
        execution_facts = format_execution_facts_section(task)
        historical_execution_facts_section = format_historical_execution_facts_section(historical_facts)
        latest_failure_note = latest_replan_failure_message(task)
        context_budget = build_context_budget_section(
            dialog_context=dialog_context,
            repository_context=repository_context,
            task=task,
        )
        repository_summary = repository_context.get("repository_summary", "")
        environment_strategy = self._build_environment_strategy_section(repository_context)
        key_files_section = build_key_files_section(repository_context)
        retrieved_section = build_retrieved_context_section(repository_context)
        preview_section = build_critical_previews_section(repository_context)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a ReAct (Reason + Act) autonomous DevOps agent. "
                    "You operate in a strict Thought → Action → Observation loop. "
                    "Each call to you is one Thought: you read all prior Observations, "
                    "reason about what they mean for the goal, and decide exactly ONE next Action. "
                    "The system will execute that action, capture the Observation, and call you again. "
                    "Return strict JSON only with keys: intent, reasoning, is_complete, completion_summary, steps. "
                    "intent keys: objective, category, complexity, needs_repository_context. "
                    "Each step keys: title, kind, command, image, parameters, requires_approval, success_criteria. "
                    "Allowed step kinds: shell, docker, github. "
                    "Rules: "
                    "1) Plan EXACTLY 1 executable step per response — this is the ReAct single-action constraint. "
                    "2) If the task is complete, set is_complete=true and return steps=[]. "
                    "3) Do not emit pseudo-steps like plan, analyze, summarize, or explain as executable steps. "
                    "4) Every step must be directly executable by the backend without extra natural language interpretation. "
                    "5) Set requires_approval=true for every emitted step. "
                    "6) Prefer inspection commands first when repository state is uncertain. "
                    "7) Prefer these shell command prefixes when possible: ls, pwd, echo, cat, rg, sed, head, tail, git, python, python3, pip, pip3, pytest, npm, node, yarn, pnpm, bash, sh. "
                    "8) Commands outside that preferred set are still allowed but require explicit human approval. "
                    "9) Use the provided repository evidence and make sure the planned step is consistent with those facts. "
                    "10) reasoning is your visible Thought for the UI: read the latest Observation in the ReAct trace, "
                    "    reflect on what succeeded or failed, then explain in one or two sentences exactly what you will do next and why. "
                    "11) Never repeat actions that already appear as completed Observations in the ReAct trace. "
                    "    If all setup steps succeeded, move to the next unmet objective or mark the task complete. "
                    "12) If latest_replan_failure_message is provided, treat it as the operator-selected failure context "
                    "    that should drive the next recovery action. "
                    "13) Treat EnvironmentStrategy as a high-priority execution constraint. "
                    "    If the user explicitly requested conda, docker, venv, poetry, pipenv, or uv, follow that preference unless it is impossible. "
                    "14) Do not silently replace a user-requested conda workflow with pip when the repository provides conda signals.",
                ),
                (
                    "human",
                    "User request:\n{user_message}\n\n"
                    "ContextBudget:\n{context_budget}\n\n"
                    "ReAct trace (Thought / Action / Observation history):\n{react_trace}\n\n"
                    "Recent dialog context:\n{dialog_context}\n\n"
                    "RepositorySummary:\n{repository_summary}\n\n"
                    "EnvironmentStrategy:\n{environment_strategy}\n\n"
                    "KeyFiles:\n{key_files}\n\n"
                    "RetrievedContext:\n{retrieved_context}\n\n"
                    "CriticalFilePreviews:\n{critical_file_previews}\n\n"
                    "Execution facts:\n{execution_facts}\n\n"
                    "Historical execution facts from previous tasks in this dialog:\n{historical_execution_facts}\n\n"
                    "Latest replan failure message:\n{latest_replan_failure_message}\n\n"
                    "Execution history:\n{execution_history}",
                ),
            ]
        )

        try:
            response = self.llm.invoke(
                prompt.format_messages(
                    user_message=user_message,
                    context_budget=context_budget,
                    react_trace=react_trace,
                    dialog_context=context_preview,
                    repository_summary=repository_summary,
                    environment_strategy=environment_strategy,
                    key_files=key_files_section,
                    retrieved_context=retrieved_section,
                    critical_file_previews=preview_section,
                    execution_facts=execution_facts,
                    historical_execution_facts=historical_execution_facts_section,
                    latest_replan_failure_message=latest_failure_note,
                    execution_history=execution_history,
                )
            )
            payload = parse_json_payload(str(response.content))
            payload = sanitize_decision_payload(payload, user_message=user_message)
            return PlannerDecisionModel.model_validate(payload)
        except Exception as exc:
            logger.warning("LLM planner failed, fallback to rule planner: %s", exc)
            return None

    def plan_next_actions_with_rules(
        self,
        *,
        task,
        user_message: str,
        repository_context: dict[str, Any],
    ) -> PlannerDecisionModel:
        lowered = user_message.lower()
        executed_titles = {step.title for step in task.steps}
        steps: list[ExecutionStepModel] = []

        from backend.app.agents.types import IntentAnalysis

        intent = IntentAnalysis(
            objective=user_message,
            category="automation",
            complexity="medium",
            needs_repository_context=True,
        )

        issue_match = re.search(r"(?:issue|pr|pull request)\s*#?(\d+)", lowered)
        workflow_match = re.search(r"workflow\s+([a-zA-Z0-9_.-]+)", user_message)

        if issue_match and "comment" in lowered and not executed_titles:
            steps.append(
                ExecutionStepModel(
                    title=f"Post comment on issue #{issue_match.group(1)}",
                    kind="github",
                    parameters={
                        "action": "create_issue_comment",
                        "issue_number": int(issue_match.group(1)),
                        "body": f"Automated message from AI DevOps Copilot:\n\n{user_message}",
                    },
                    success_criteria="A GitHub issue comment is created successfully.",
                )
            )
            intent.category = "github_comment"
        elif "workflow" in lowered and ("trigger" in lowered or "dispatch" in lowered) and not executed_titles:
            steps.append(
                ExecutionStepModel(
                    title="Trigger GitHub Actions workflow",
                    kind="github",
                    parameters={
                        "action": "dispatch_workflow",
                        "workflow_id": workflow_match.group(1) if workflow_match else "ci.yml",
                    },
                    success_criteria="The workflow dispatch API accepts the workflow run.",
                )
            )
            intent.category = "github_actions"
        else:
            install_command = repository_context["install_command"]
            test_command = repository_context["test_command"]

            if any(
                token in lowered
                for token in [
                    "install",
                    "setup",
                    "environment",
                    "dependencies",
                    "conda",
                    "poetry",
                    "pipenv",
                    "venv",
                    "uv",
                ]
            ) and "Install dependencies" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Install dependencies",
                        kind="shell",
                        command=install_command,
                        success_criteria="Dependencies install without command failure.",
                    )
                )

            if any(token in lowered for token in ["test", "pytest", "unit test", "run tests"]) and "Run tests and capture failure points" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Run tests and capture failure points",
                        kind="shell",
                        command=test_command,
                        success_criteria="The test command runs and returns actionable output.",
                    )
                )

            if ("docker" in lowered or "container" in lowered) and "Run containerized validation command" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Run containerized validation command",
                        kind="docker",
                        image="python:3.10-slim"
                        if repository_context.get("runtime_focus") == "python"
                        else "node:20-alpine",
                        command=test_command,
                        success_criteria="The command executes successfully inside the container.",
                    )
                )

            if not steps and "Inspect repository workspace" not in executed_titles:
                steps.append(
                    ExecutionStepModel(
                        title="Inspect repository workspace",
                        kind="shell",
                        command="ls -la",
                        success_criteria="Workspace contents are listed for further planning.",
                    )
                )

        return PlannerDecisionModel(
            intent=intent,
            reasoning="Rule-based fallback planner generated the next executable steps.",
            is_complete=bool(task.steps) and not steps,
            completion_summary="Rule planner determined there are no more safe executable steps."
            if bool(task.steps) and not steps
            else None,
            steps=steps,
        )

    def normalize_decision(
        self,
        *,
        decision: PlannerDecisionModel,
        task,
        historical_execution_facts: dict[str, Any] | None = None,
    ) -> PlannerDecisionModel:
        execution_facts = build_execution_facts(task)
        merged_execution_facts = merge_execution_facts(execution_facts, historical_execution_facts or {})
        completed_signatures = set(merged_execution_facts["completed_signatures"])
        safe_steps: list[ExecutionStepModel] = []
        for raw_step in decision.steps:
            try:
                step = ExecutionStepModel.model_validate(raw_step)
            except ValidationError:
                continue

            if is_redundant_completed_step(step, completed_signatures):
                continue
            step.requires_approval = True
            safe_steps.append(step)

        if len(safe_steps) > 1:
            logger.warning(
                "Planner returned %s steps for task %s; keeping only the first step to enforce the single-action ReAct loop.",
                len(safe_steps),
                task.id,
            )
            safe_steps = safe_steps[:1]

        if not safe_steps and not decision.is_complete:
            if should_mark_setup_complete(task, merged_execution_facts):
                return PlannerDecisionModel(
                    intent=decision.intent,
                    reasoning=decision.reasoning,
                    is_complete=True,
                    completion_summary=(
                        decision.completion_summary
                        or "Environment setup steps already completed successfully; no further setup action is needed."
                    ),
                    steps=[],
                )
            safe_steps = [
                ExecutionStepModel(
                    title="Inspect repository workspace",
                    kind="shell",
                    command="ls -la",
                    success_criteria="Workspace contents are listed for further planning.",
                )
            ]

        return PlannerDecisionModel(
            intent=decision.intent,
            reasoning=decision.reasoning,
            is_complete=decision.is_complete and not safe_steps,
            completion_summary=decision.completion_summary,
            steps=safe_steps,
        )

    def execute_step(
        self,
        *,
        plan_step: ExecutionStepModel,
        owner: str,
        name: str,
        branch: str,
        task_id: str | None = None,
        on_output=None,
    ) -> ToolResult:
        if plan_step.kind == "shell":
            result = self.executor.execute(
                request=self.executor_request(
                    command=plan_step.command or "",
                    owner=owner,
                    repository_name=name,
                    branch=branch,
                    task_id=task_id,
                    on_output=on_output,
                )
            )
            return ToolResult(
                step=plan_step.title,
                success=result.success,
                output=result.stdout or result.stderr,
                error=result.stderr if not result.success else None,
                metadata=result.metadata,
            )

        if plan_step.kind == "docker":
            result = self.executor.run_docker(
                image=plan_step.image or "python:3.10-slim",
                command=plan_step.command,
                working_directory=self.ensure_workspace(owner, name, branch, task_id=task_id),
                on_output=on_output,
            )
            return ToolResult(
                step=plan_step.title,
                success=result.success,
                output=result.stdout or result.stderr,
                error=result.stderr if not result.success else None,
                metadata=result.metadata,
            )

        if plan_step.kind == "github":
            context = GitHubContext(owner=owner, name=name, branch=branch)
            action = plan_step.parameters.get("action") or self.infer_github_action(plan_step)
            if action == "create_issue_comment":
                body = plan_step.parameters.get("body") or plan_step.parameters.get("comment_body") or plan_step.command
                response = self.github_service.create_issue_comment(
                    context,
                    issue_number=plan_step.parameters["issue_number"],
                    body=body,
                )
            elif action == "dispatch_workflow":
                response = self.github_service.dispatch_workflow(
                    context,
                    workflow_id=plan_step.parameters["workflow_id"],
                    ref=branch,
                )
            elif action == "create_pull_request":
                response = self.github_service.create_pull_request(
                    context,
                    title=plan_step.parameters["title"],
                    body=plan_step.parameters["body"],
                    head=plan_step.parameters["head"],
                    base=plan_step.parameters.get("base", branch),
                )
            else:
                raise ValueError(f"Unsupported GitHub action: {action}")

            return ToolResult(
                step=plan_step.title,
                success=True,
                output=json.dumps(response, indent=2),
                metadata=response,
            )

        raise ValueError(f"Unsupported step kind: {plan_step.kind}")

    def executor_request(
        self,
        *,
        command: str,
        owner: str,
        repository_name: str,
        branch: str,
        task_id: str | None = None,
        on_output=None,
    ):
        working_directory = self.ensure_workspace(owner, repository_name, branch, task_id=task_id)
        return self.executor_request_class(
            command,
            working_directory,
            allow_unlisted_command=True,
            on_output=on_output,
        )

    @property
    def executor_request_class(self):
        from backend.app.executors.base import ExecutionRequest

        return ExecutionRequest

    def build_summary(
        self,
        *,
        user_message: str,
        results: list[dict[str, Any]],
        completion_summary: str | None = None,
    ) -> str:
        result_digest = self._build_summary_result_digest(results)
        if self.llm is None:
            lines = [f"Request: {user_message}"]
            if completion_summary:
                lines.append(f"Outcome: {completion_summary}")
            lines.extend(
                [
                    f"Completed steps: {result_digest['completed_steps']}",
                    f"Failed steps: {result_digest['failed_steps']}",
                    "",
                    "Step summary:",
                ]
            )
            for step in result_digest["steps"]:
                prefix = "OK" if step["success"] else "FAILED"
                lines.append(f"- [{prefix}] {step['step']}: {step['outcome']}")
            return "\n".join(lines)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You summarize DevOps automation runs for humans. "
                    "Return a concise summary in 2-4 sentences. "
                    "Focus on the overall outcome, the important actions taken, and any notable failure or follow-up. "
                    "Do not quote or reproduce raw command output, terminal logs, stack traces, JSON payloads, or long file lists. "
                    "Do not mirror the command line output back to the user. "
                    "Summarize what happened; do not transcribe it.",
                ),
                (
                    "human",
                    "User request: {user_message}\n\n"
                    "Completion signal: {completion_summary}\n\n"
                    "Execution digest:\n{results}\n\n"
                    "Write a true summary, not a replay of terminal output.",
                ),
            ]
        )
        response = self.llm.invoke(
            prompt.format_messages(
                user_message=user_message,
                completion_summary=completion_summary or "No explicit completion signal provided.",
                results=json.dumps(result_digest, indent=2),
            )
        )
        return str(response.content)

    def ensure_workspace(self, owner: str, name: str, branch: str, *, task_id: str | None = None) -> str:
        if task_id:
            workspace = self.worktree_manager.ensure_task_worktree(
                owner=owner,
                name=name,
                branch=branch,
                task_id=task_id,
            )
            return workspace["worktree_path"]

        workspace = self.worktree_manager.ensure_shared_workspace(
            owner=owner,
            name=name,
            branch=branch,
        )
        return workspace["worktree_path"]

    def infer_github_action(self, step: ExecutionStepModel) -> str | None:
        parameters = step.parameters or {}
        if "issue_number" in parameters and ("body" in parameters or "comment_body" in parameters or step.command):
            return "create_issue_comment"
        if "workflow_id" in parameters:
            return "dispatch_workflow"
        if {"title", "body", "head"}.issubset(parameters.keys()):
            return "create_pull_request"
        return None

    def requires_approval(self, step: ExecutionStepModel) -> bool:
        approval_mode = get_or_create_app_settings(self.db).approval_mode
        if approval_mode == ApprovalMode.ALL_ALLOW:
            return False
        if approval_mode == ApprovalMode.NO:
            return True
        if step.kind == "github":
            return True
        if step.kind in {"shell", "docker"}:
            first_token = self.command_first_token(step.command or "")
            return bool(first_token and first_token not in self.settings.command_allowlist)
        return True

    def command_first_token(self, command: str) -> str | None:
        try:
            return re.split(r"\s+", command.strip(), maxsplit=1)[0] or None
        except Exception:
            return None

    def _build_repository_signal_text(self, base_context: dict[str, Any]) -> str:
        parts = [str(base_context.get("repository_summary") or "")]
        for collection_name in ("retrieved_context", "critical_file_previews"):
            for item in base_context.get(collection_name, []):
                if isinstance(item, dict):
                    parts.append(str(item.get("source") or ""))
                    parts.append(str(item.get("content") or ""))
        return "\n".join(part for part in parts if part).lower()

    def _detect_environment_strategy(
        self,
        *,
        user_message: str,
        lower_paths: list[str],
        lower_filenames: set[str],
        context_text: str,
        stack: str,
    ) -> dict[str, Any]:
        user_preference = self._detect_user_environment_preference(user_message)
        environment_file = self._pick_first_matching_path(
            lower_paths,
            suffixes=("environment.yml", "environment.yaml", "pipfile", "poetry.lock", "uv.lock", "requirements.txt"),
        )
        environment_name = self._extract_environment_name(context_text)
        runtime_focus = self._infer_runtime_focus(
            user_message=user_message,
            stack=stack,
            environment_preference=user_preference,
        )

        if user_preference == "conda":
            return self._build_environment_strategy_payload(
                environment_manager="conda",
                environment_reason="user_requested_conda",
                environment_name=environment_name,
                environment_file=environment_file
                if environment_file and environment_file.endswith(("environment.yml", "environment.yaml"))
                else self._pick_first_matching_path(lower_paths, suffixes=("environment.yml", "environment.yaml")),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if user_preference in {"venv", "pip", "poetry", "pipenv", "uv"}:
            return self._build_environment_strategy_payload(
                environment_manager=user_preference,
                environment_reason=f"user_requested_{user_preference}",
                environment_name=environment_name,
                environment_file=environment_file,
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )

        if self._has_path_suffix(lower_paths, ("environment.yml", "environment.yaml")) or "conda" in context_text:
            return self._build_environment_strategy_payload(
                environment_manager="conda",
                environment_reason="repository_conda_signals",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("environment.yml", "environment.yaml")),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if "poetry.lock" in lower_filenames or "[tool.poetry]" in context_text:
            return self._build_environment_strategy_payload(
                environment_manager="poetry",
                environment_reason="repository_poetry_signals",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("pyproject.toml", "poetry.lock")),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if "pipfile" in lower_filenames:
            return self._build_environment_strategy_payload(
                environment_manager="pipenv",
                environment_reason="repository_pipenv_signals",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("pipfile",)),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if "uv.lock" in lower_filenames or re.search(r"\buv\b", context_text):
            return self._build_environment_strategy_payload(
                environment_manager="uv",
                environment_reason="repository_uv_signals",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("uv.lock", "pyproject.toml")),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if "requirements.txt" in lower_filenames or runtime_focus == "python":
            return self._build_environment_strategy_payload(
                environment_manager="pip",
                environment_reason="repository_python_defaults",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("requirements.txt",)),
                runtime_focus=runtime_focus,
                lower_paths=lower_paths,
            )
        if stack in {"node", "polyglot"}:
            return self._build_environment_strategy_payload(
                environment_manager="npm",
                environment_reason="repository_node_defaults",
                environment_name=environment_name,
                environment_file=self._pick_first_matching_path(lower_paths, suffixes=("package.json",)),
                runtime_focus="node",
                lower_paths=lower_paths,
            )
        return self._build_environment_strategy_payload(
            environment_manager="generic",
            environment_reason="no_specific_environment_signals",
            environment_name=environment_name,
            environment_file=environment_file,
            runtime_focus=runtime_focus,
            lower_paths=lower_paths,
        )

    def _build_environment_strategy_payload(
        self,
        *,
        environment_manager: str,
        environment_reason: str,
        environment_name: str | None,
        environment_file: str | None,
        runtime_focus: str,
        lower_paths: list[str],
    ) -> dict[str, Any]:
        install_command = "echo 'Inspect environment setup before installing dependencies.'"
        test_command = "pytest" if runtime_focus == "python" else "npm test" if runtime_focus == "node" else "pytest"

        if environment_manager == "conda":
            setup_script = self._pick_first_matching_path(lower_paths, suffixes=("scripts/setup-conda.sh",))
            if setup_script:
                install_command = f'./{setup_script}'
            elif environment_file:
                install_command = f'conda env create -f "{environment_file}"'
            else:
                install_command = "conda env list"
            if runtime_focus == "python":
                test_command = (
                    f'conda run -n {environment_name} pytest'
                    if environment_name
                    else "pytest"
                )
        elif environment_manager == "poetry":
            install_command = "poetry install"
            test_command = "poetry run pytest" if runtime_focus == "python" else "poetry run npm test"
        elif environment_manager == "pipenv":
            install_command = "pipenv install"
            test_command = "pipenv run pytest" if runtime_focus == "python" else "pipenv run npm test"
        elif environment_manager == "uv":
            install_command = "uv sync"
            test_command = "uv run pytest" if runtime_focus == "python" else "uv run npm test"
        elif environment_manager == "venv":
            install_command = "python -m venv .venv"
            test_command = "pytest"
        elif environment_manager == "pip":
            install_command = "pip install -r requirements.txt"
            test_command = "pytest"
        elif environment_manager == "npm":
            install_command = "npm install"
            test_command = "npm test"

        return {
            "environment_manager": environment_manager,
            "environment_reason": environment_reason,
            "environment_name": environment_name,
            "environment_file": environment_file,
            "runtime_focus": runtime_focus,
            "install_command": install_command,
            "test_command": test_command,
        }

    def _infer_runtime_focus(self, *, user_message: str, stack: str, environment_preference: str | None) -> str:
        lowered = user_message.lower()
        python_tokens = {
            "python",
            "conda",
            "pip",
            "pytest",
            "train",
            "model",
            "database",
            "backend",
            "celery",
            "fastapi",
        }
        node_tokens = {
            "node",
            "npm",
            "frontend",
            "next.js",
            "react",
            "typescript",
            "tailwind",
            "eslint",
            "web",
        }
        python_score = sum(token in lowered for token in python_tokens)
        node_score = sum(token in lowered for token in node_tokens)

        if environment_preference in {"conda", "venv", "pip", "poetry", "pipenv", "uv"}:
            return "python"
        if environment_preference == "npm":
            return "node"
        if python_score > node_score:
            return "python"
        if node_score > python_score:
            return "node"
        if stack == "polyglot":
            return "python"
        return stack

    def _detect_user_environment_preference(self, user_message: str) -> str | None:
        lowered = user_message.lower()
        if "conda" in lowered:
            return "conda"
        if "poetry" in lowered:
            return "poetry"
        if "pipenv" in lowered:
            return "pipenv"
        if re.search(r"\buv\b", lowered):
            return "uv"
        if "venv" in lowered or "virtualenv" in lowered:
            return "venv"
        if "pip " in lowered or lowered.endswith("pip"):
            return "pip"
        if "npm" in lowered or "node" in lowered:
            return "npm"
        return None

    def _build_environment_strategy_section(self, repository_context: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"- runtime_focus: {repository_context.get('runtime_focus', 'generic')}",
                f"- environment_manager: {repository_context.get('environment_manager', 'generic')}",
                f"- environment_reason: {repository_context.get('environment_reason', 'unknown')}",
                f"- environment_name: {repository_context.get('environment_name') or 'unknown'}",
                f"- environment_file: {repository_context.get('environment_file') or 'none'}",
                f"- install_command: {repository_context.get('install_command') or 'none'}",
                f"- test_command: {repository_context.get('test_command') or 'none'}",
            ]
        )

    def _pick_first_matching_path(self, lower_paths: list[str], *, suffixes: tuple[str, ...]) -> str | None:
        for path in lower_paths:
            if path.endswith(suffixes):
                return path.lstrip("./")
        return None

    def _has_path_suffix(self, lower_paths: list[str], suffixes: tuple[str, ...]) -> bool:
        return self._pick_first_matching_path(lower_paths, suffixes=suffixes) is not None

    def _extract_environment_name(self, context_text: str) -> str | None:
        match = re.search(r"(?m)^name:\s*([A-Za-z0-9_.-]+)\s*$", context_text)
        if match:
            return match.group(1)
        return None

    def _build_summary_result_digest(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total_steps": len(results),
            "completed_steps": sum(1 for result in results if bool(result.get("success"))),
            "failed_steps": sum(1 for result in results if not bool(result.get("success"))),
            "steps": [
                {
                    "step": str(result.get("step") or "Unnamed step"),
                    "success": bool(result.get("success")),
                    "outcome": self._summarize_result_text(result),
                }
                for result in results
            ],
        }

    def _summarize_result_text(self, result: dict[str, Any]) -> str:
        error = self._normalize_summary_text(result.get("error"))
        if error:
            return error

        output = self._normalize_summary_text(result.get("output"), prefer_last=True)
        if output:
            return output

        return "Step completed without additional output."

    def _normalize_summary_text(self, value: Any, *, limit: int = 120, prefer_last: bool = False) -> str:
        if not isinstance(value, str):
            return ""

        lines = value.splitlines()
        candidate_lines = list(reversed(lines)) if prefer_last else lines

        for line in candidate_lines:
            cleaned = " ".join(line.strip().split())
            if cleaned:
                if self._should_skip_summary_line(cleaned):
                    continue
                if len(cleaned) <= limit:
                    return cleaned
                return f"{cleaned[:limit - 3]}..."

        return ""

    def _should_skip_summary_line(self, line: str) -> bool:
        if line.startswith(("$ ", "> ")):
            return True
        if re.fullmatch(r"[=\-]{4,}", line):
            return True
        if re.match(r"=+", line):
            return True
        if re.fullmatch(r"collected \d+ items", line):
            return True
        return False
