from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field


StepKind = Literal["shell", "docker", "github"]


class IntentAnalysis(BaseModel):
    objective: str
    category: str
    complexity: Literal["low", "medium", "high"] = "medium"
    needs_repository_context: bool = True


class ExecutionStepModel(BaseModel):
    title: str
    kind: StepKind
    command: str | None = None
    image: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True
    success_criteria: str | None = None


class ExecutionPlanModel(BaseModel):
    intent: IntentAnalysis
    repository_context: dict[str, Any] = Field(default_factory=dict)
    steps: list[ExecutionStepModel] = Field(default_factory=list)
    planner_iterations: list[dict[str, Any]] = Field(default_factory=list)


class PlannerDecisionModel(BaseModel):
    intent: IntentAnalysis
    reasoning: str
    is_complete: bool = False
    steps: list[ExecutionStepModel] = Field(default_factory=list)
    completion_summary: str | None = None


class ToolResult(BaseModel):
    step: str
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGraphState(TypedDict):
    task_id: str
    user_message: str
    owner: str
    name: str
    branch: str
    dialog_context: list[str]
    historical_execution_facts: dict[str, Any]
    repository_context: dict[str, Any]
    plan: dict[str, Any]
    results: list[dict[str, Any]]
    summary: str
    waiting_for_human: bool
    is_complete: bool
    iteration_count: int
    completion_summary: str
