from pathlib import Path

import pytest

from backend.app.executors.base import ExecutionRequest
from backend.app.executors.local import LocalExecutor


def test_local_executor_runs_allowlisted_command(tmp_path: Path) -> None:
    executor = LocalExecutor()
    request = ExecutionRequest(command="echo hello", working_directory=tmp_path.as_posix())

    result = executor.execute(request)

    assert result.success is True
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_local_executor_blocks_dangerous_command(tmp_path: Path) -> None:
    executor = LocalExecutor()
    request = ExecutionRequest(command="rm -rf /", working_directory=tmp_path.as_posix())

    with pytest.raises(ValueError):
        executor.execute(request)


def test_local_executor_allows_unlisted_command_after_override(tmp_path: Path) -> None:
    executor = LocalExecutor()
    request = ExecutionRequest(
        command="cat missing-file.txt",
        working_directory=tmp_path.as_posix(),
        allow_unlisted_command=True,
    )

    result = executor.execute(request)

    assert result.success is False
    assert result.exit_code != 0
    assert result.metadata["allow_unlisted_command"] is True
