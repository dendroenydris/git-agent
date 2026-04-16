from backend.app.executors.base import BaseExecutor, ExecutionRequest, ExecutionResult


class SandboxExecutor(BaseExecutor):
    """Reserved extension point for per-task isolated containers."""

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError("SandboxExecutor is not implemented yet")

    def run_docker(self, *, image: str, command: str | None, working_directory: str) -> ExecutionResult:
        raise NotImplementedError("SandboxExecutor is not implemented yet")
