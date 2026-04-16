from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionRequest:
    command: str
    working_directory: str
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 900
    allow_unlisted_command: bool = False


@dataclass
class ExecutionResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseExecutor(ABC):
    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def run_docker(self, *, image: str, command: str | None, working_directory: str) -> ExecutionResult:
        raise NotImplementedError
