from enum import Enum


class MessageType(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_HUMAN = "waiting_for_human"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalMode(str, Enum):
    ALL_ALLOW = "all-allow"
    ALLOW_ALLOWLIST = "allow-allowlist"
    NO = "no"


class ExecutionKind(str, Enum):
    PLAN = "plan"
    SHELL = "shell"
    DOCKER = "docker"
    GITHUB = "github"
    SUMMARY = "summary"
