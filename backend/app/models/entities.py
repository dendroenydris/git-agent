from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.models.enums import (
    ApprovalMode,
    ApprovalStatus,
    MessageType,
    StepStatus,
    TaskStatus,
)


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("repo"))
    owner: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    branch: Mapped[str] = mapped_column(String(255), default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    dialogs: Mapped[list[Dialog]] = relationship(back_populates="repository")
    indices: Mapped[list[RepositoryIndex]] = relationship(back_populates="repository")


class RepositoryIndex(Base):
    __tablename__ = "repository_indices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("index"))
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    vectorstore_path: Mapped[str] = mapped_column(String(1024))
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    repository: Mapped[Repository] = relationship(back_populates="indices")


class Dialog(Base):
    __tablename__ = "dialogs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("dialog"))
    title: Mapped[str] = mapped_column(String(255))
    repository_id: Mapped[str | None] = mapped_column(ForeignKey("repositories.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    repository: Mapped[Repository | None] = relationship(back_populates="dialogs")
    messages: Mapped[list[Message]] = relationship(
        back_populates="dialog", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    tasks: Mapped[list[TaskRun]] = relationship(
        back_populates="dialog", cascade="all, delete-orphan", order_by="TaskRun.created_at"
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="global")
    approval_mode: Mapped[ApprovalMode] = mapped_column(
        Enum(ApprovalMode), default=ApprovalMode.NO
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("msg"))
    dialog_id: Mapped[str] = mapped_column(ForeignKey("dialogs.id"), index=True)
    type: Mapped[MessageType] = mapped_column(Enum(MessageType), index=True)
    content: Mapped[str] = mapped_column(Text)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    dialog: Mapped[Dialog] = relationship(back_populates="messages")
    task: Mapped[TaskRun | None] = relationship(back_populates="messages")


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("task"))
    dialog_id: Mapped[str] = mapped_column(ForeignKey("dialogs.id"), index=True)
    repository_id: Mapped[str | None] = mapped_column(ForeignKey("repositories.id"), index=True)
    user_message: Mapped[str] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.QUEUED)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), default=ApprovalStatus.NOT_REQUIRED
    )
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dialog: Mapped[Dialog] = relationship(back_populates="tasks")
    repository: Mapped[Repository | None] = relationship()
    steps: Mapped[list[TaskStep]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.position"
    )
    messages: Mapped[list[Message]] = relationship(back_populates="task")


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: generate_id("step"))
    task_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.PENDING)
    kind: Mapped[str] = mapped_column(String(64), default="plan")
    command: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    task: Mapped[TaskRun] = relationship(back_populates="steps")
