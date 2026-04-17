from __future__ import annotations

import os
import shlex
import subprocess
import threading

from backend.app.core.config import get_settings
from backend.app.executors.base import BaseExecutor, ExecutionRequest, ExecutionResult, OutputCallback


class LocalExecutor(BaseExecutor):
    def __init__(self) -> None:
        self.settings = get_settings()

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self._validate_command(
            request.command,
            allow_unlisted_command=request.allow_unlisted_command,
        )
        process = subprocess.Popen(
            ["/bin/bash", "-lc", request.command],
            cwd=request.working_directory,
            env={**os.environ, **request.environment},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout, stderr, return_code = self._collect_process_output(
            process=process,
            timeout_seconds=request.timeout_seconds,
            on_output=request.on_output,
        )
        return ExecutionResult(
            success=return_code == 0,
            exit_code=return_code,
            stdout=stdout,
            stderr=stderr,
            metadata={
                "working_directory": request.working_directory,
                "allow_unlisted_command": request.allow_unlisted_command,
            },
        )

    def run_docker(
        self,
        *,
        image: str,
        command: str | None,
        working_directory: str,
        on_output: OutputCallback | None = None,
    ) -> ExecutionResult:
        docker_command = ["docker", "run", "--rm", "-v", f"{working_directory}:/workspace", "-w", "/workspace", image]
        if command:
            docker_command.extend(shlex.split(command))

        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout, stderr, return_code = self._collect_process_output(
            process=process,
            timeout_seconds=self.settings.execution_timeout_seconds,
            on_output=on_output,
        )
        return ExecutionResult(
            success=return_code == 0,
            exit_code=return_code,
            stdout=stdout,
            stderr=stderr,
            metadata={"image": image, "working_directory": working_directory},
        )

    def _collect_process_output(
        self,
        *,
        process: subprocess.Popen[str],
        timeout_seconds: int,
        on_output: OutputCallback | None,
    ) -> tuple[str, str, int]:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _reader(stream_name: str, stream) -> None:
            try:
                for chunk in iter(stream.readline, ""):
                    if not chunk:
                        break
                    if stream_name == "stdout":
                        stdout_chunks.append(chunk)
                    else:
                        stderr_chunks.append(chunk)
                    if on_output:
                        on_output(stream_name, chunk)
            finally:
                if stream is not None:
                    stream.close()

        stdout_thread = threading.Thread(
            target=_reader,
            args=("stdout", process.stdout),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_reader,
            args=("stderr", process.stderr),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
            timeout_message = f"\nCommand timed out after {timeout_seconds} seconds.\n"
            stderr_chunks.append(timeout_message)
            if on_output:
                on_output("stderr", timeout_message)

        stdout_thread.join()
        stderr_thread.join()

        return "".join(stdout_chunks), "".join(stderr_chunks), return_code

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
