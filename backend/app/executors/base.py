from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


OutputCallback = Callable[[str, str], None]


@dataclass
class ExecutionRequest:
    command: str
    working_directory: str
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 900
    allow_unlisted_command: bool = False
    on_output: OutputCallback | None = None


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
    def run_docker(
        self,
        *,
        image: str,
        command: str | None,
        working_directory: str,
        on_output: OutputCallback | None = None,
    ) -> ExecutionResult:
        raise NotImplementedError
