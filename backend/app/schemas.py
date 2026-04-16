from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.enums import ApprovalMode, ApprovalStatus, MessageType, StepStatus, TaskStatus


class RepositoryRef(BaseModel):
    owner: str
    name: str
    branch: str = "main"


class DialogCreate(BaseModel):
    owner: str
    name: str
    branch: str = "main"


class AgentMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: MessageType
    content: str
    created_at: datetime
    task_id: str | None = None
    summary: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TaskStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    title: str
    status: StepStatus
    kind: str
    command: str | None = None
    output: str | None = None
    error: str | None = None
    requires_approval: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class WorkflowPlanRead(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list)
    intent: dict[str, Any] = Field(default_factory=dict)
    repository_context: dict[str, Any] = Field(default_factory=dict)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dialog_id: str
    repository_id: str | None = None
    user_message: str
    status: TaskStatus
    approval_status: ApprovalStatus
    plan_json: dict[str, Any] = Field(default_factory=dict)
    result_json: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    error: str | None = None
    current_step_index: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    steps: list[TaskStepRead] = Field(default_factory=list)


class DialogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    repo: RepositoryRef | None = None
    messages: list[AgentMessageRead] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str


class ChatAccepted(BaseModel):
    mode: str = "task"
    task_id: str
    dialog_id: str
    status: TaskStatus


class ChatAnswer(BaseModel):
    mode: str = "answer"
    dialog_id: str
    status: str = "completed"
    answer: str


class ApprovalRequest(BaseModel):
    approved: bool
    reason: str | None = None


class ReplanTaskRequest(BaseModel):
    failure_message: str


class TaskActionResponse(BaseModel):
    task_id: str
    status: TaskStatus
    approval_status: ApprovalStatus


class AppSettingsRead(BaseModel):
    approval_mode: ApprovalMode


class AppSettingsUpdate(BaseModel):
    approval_mode: ApprovalMode


class HealthResponse(BaseModel):
    status: str
    redis: str
    database: str
    version: str = "2.0.0"


class RepositoryIndexRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repository_id: str
    status: str
    commit_sha: str | None = None
    vectorstore_path: str
    total_files: int
    total_chunks: int
    summary: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TaskEvent(BaseModel):
    type: str
    dialog_id: str | None = None
    task_id: str | None = None
    message_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
