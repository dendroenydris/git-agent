from __future__ import annotations

import os
import shlex
import subprocess

from backend.app.core.config import get_settings
from backend.app.executors.base import BaseExecutor, ExecutionRequest, ExecutionResult


class LocalExecutor(BaseExecutor):
    def __init__(self) -> None:
        self.settings = get_settings()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self._validate_command(
            request.command,
            allow_unlisted_command=request.allow_unlisted_command,
        )
        process = subprocess.run(
            ["/bin/bash", "-lc", request.command],
            cwd=request.working_directory,
            env={**os.environ, **request.environment},
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
        )
        return ExecutionResult(
            success=process.returncode == 0,
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            metadata={
                "working_directory": request.working_directory,
                "allow_unlisted_command": request.allow_unlisted_command,
            },
        )

    def run_docker(self, *, image: str, command: str | None, working_directory: str) -> ExecutionResult:
        docker_command = ["docker", "run", "--rm", "-v", f"{working_directory}:/workspace", "-w", "/workspace", image]
        if command:
            docker_command.extend(shlex.split(command))

        process = subprocess.run(
            docker_command,
            capture_output=True,
            text=True,
            timeout=self.settings.execution_timeout_seconds,
        )
        return ExecutionResult(
            success=process.returncode == 0,
            exit_code=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            metadata={"image": image, "working_directory": working_directory},
        )

    def _validate_command(self, command: str, *, allow_unlisted_command: bool) -> None:
        lowered = command.lower()
        if any(dangerous in lowered for dangerous in self.settings.dangerous_commands):
            raise ValueError("Command rejected by safety policy")

        first_token = shlex.split(command)[0]
        if first_token not in self.settings.command_allowlist and not allow_unlisted_command:
            raise ValueError(
                f"Command '{first_token}' is not in the execution allowlist. "
                "Update command_allowlist to permit it."
            )
