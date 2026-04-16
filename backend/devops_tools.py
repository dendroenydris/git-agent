from backend.app.executors.base import ExecutionRequest
from backend.app.executors.local import LocalExecutor


class DevOpsToolManager:
    def __init__(self) -> None:
        self.executor = LocalExecutor()

    async def execute_shell_script(self, script_content: str, working_directory: str | None = None, task_id: str | None = None, environment: dict | None = None) -> dict:
        del task_id
        result = self.executor.execute(
            ExecutionRequest(
                command=script_content,
                working_directory=working_directory or ".",
                environment=environment or {},
            )
        )
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "metadata": result.metadata,
        }

    async def run_docker_container(self, image: str, command: str | None = None, volumes: list | None = None, ports: dict | None = None, task_id: str | None = None) -> dict:
        del volumes, ports, task_id
        result = self.executor.run_docker(image=image, command=command, working_directory=".")
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "metadata": result.metadata,
        }


devops_manager = DevOpsToolManager()