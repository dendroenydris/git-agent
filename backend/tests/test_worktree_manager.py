from pathlib import Path
from types import SimpleNamespace

import git

from backend.app.services.worktree_manager import WorktreeManager


def _create_local_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    repository = git.Repo.init(path)
    (path / "README.md").write_text("hello\n")
    repository.index.add(["README.md"])
    repository.index.commit("init")
    repository.git.branch("-M", "main")
    return path


def test_worktree_manager_creates_isolated_task_worktrees(tmp_path: Path) -> None:
    base_repo_path = _create_local_repo(tmp_path / "repositories" / "acme__demo")
    manager = WorktreeManager()
    manager.settings = SimpleNamespace(repo_cache_dir=tmp_path / "repositories", github_token=None)
    manager._ensure_base_repo = lambda owner, name, branch: base_repo_path  # type: ignore[method-assign]

    first = manager.ensure_task_worktree(owner="acme", name="demo", branch="main", task_id="task_1")
    second = manager.ensure_task_worktree(owner="acme", name="demo", branch="main", task_id="task_2")

    assert first["base_repo_path"] == base_repo_path.as_posix()
    assert Path(first["worktree_path"]).exists()
    assert Path(second["worktree_path"]).exists()
    assert first["worktree_path"] != second["worktree_path"]

