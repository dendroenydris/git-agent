from __future__ import annotations

from typing import Any

from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.tools import StructuredTool

from backend.app.agents.orchestrator import AgentOrchestrator
from backend.app.agents.types import ExecutionStepModel


class ShellToolInput(BaseModel):
    title: str
    command: str


class DockerToolInput(BaseModel):
    title: str
    image: str = "python:3.10-slim"
    command: str | None = None


class GitHubToolInput(BaseModel):
    title: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class GraphToolbox:
    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        *,
        owner: str,
        name: str,
        branch: str,
        task_id: str,
    ) -> None:
        self.orchestrator = orchestrator
        self.owner = owner
        self.name = name
        self.branch = branch
        self.task_id = task_id
        self.tools = {
            "shell.execute": StructuredTool.from_function(
                func=self.shell_execute,
                name="shell.execute",
                description="Execute a shell command inside the task worktree.",
                args_schema=ShellToolInput,
            ),
            "docker.run": StructuredTool.from_function(
                func=self.docker_run,
                name="docker.run",
                description="Run a Docker command inside the task worktree.",
                args_schema=DockerToolInput,
            ),
            "github.action": StructuredTool.from_function(
                func=self.github_action,
                name="github.action",
                description="Run a GitHub action through the repository GitHub service.",
                args_schema=GitHubToolInput,
            ),
        }

    def get_tool(self, tool_name: str) -> StructuredTool:
        if tool_name not in self.tools:
            raise ValueError(f"Unknown graph tool: {tool_name}")
        return self.tools[tool_name]

    def shell_execute(self, title: str, command: str) -> dict[str, Any]:
        result = self.orchestrator._execute_step(
            plan_step=ExecutionStepModel(title=title, kind="shell", command=command),
            owner=self.owner,
            name=self.name,
            branch=self.branch,
            task_id=self.task_id,
        )
        return result.model_dump()

    def docker_run(self, title: str, image: str = "python:3.10-slim", command: str | None = None) -> dict[str, Any]:
        result = self.orchestrator._execute_step(
            plan_step=ExecutionStepModel(title=title, kind="docker", image=image, command=command),
            owner=self.owner,
            name=self.name,
            branch=self.branch,
            task_id=self.task_id,
        )
        return result.model_dump()

    def github_action(self, title: str, action: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.orchestrator._execute_step(
            plan_step=ExecutionStepModel(
                title=title,
                kind="github",
                parameters={"action": action, **(parameters or {})},
            ),
            owner=self.owner,
            name=self.name,
            branch=self.branch,
            task_id=self.task_id,
        )
        return result.model_dump()
