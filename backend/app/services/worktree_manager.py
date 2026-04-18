from __future__ import annotations

import logging
from pathlib import Path

import git

from backend.app.core.config import get_settings


logger = logging.getLogger(__name__)


class WorktreeManager:
    def __init__(self) -> None:
        self.settings = get_settings()

    def get_base_repo_path(self, *, owner: str, name: str) -> Path:
        return self.settings.repo_cache_dir / f"{owner}__{name}"

    def get_worktree_root(self, *, owner: str, name: str) -> Path:
        return self.settings.repo_cache_dir / "_worktrees" / f"{owner}__{name}"

    def get_task_worktree_path(self, *, owner: str, name: str, task_id: str) -> Path:
        return self.get_worktree_root(owner=owner, name=name) / task_id

    def ensure_shared_workspace(self, *, owner: str, name: str, branch: str) -> dict[str, str]:
        base_repo_path = self._ensure_base_repo(owner=owner, name=name, branch=branch)
        return self._build_metadata(base_repo_path=base_repo_path, worktree_path=base_repo_path, branch=branch)

    def ensure_task_worktree(self, *, owner: str, name: str, branch: str, task_id: str) -> dict[str, str]:
        base_repo_path = self._ensure_base_repo(owner=owner, name=name, branch=branch)
        worktree_root = self.get_worktree_root(owner=owner, name=name)
        worktree_root.mkdir(parents=True, exist_ok=True)
        worktree_path = self.get_task_worktree_path(owner=owner, name=name, task_id=task_id)

        if worktree_path.exists():
            return self._build_metadata(base_repo_path=base_repo_path, worktree_path=worktree_path, branch=branch)

        repository = git.Repo(base_repo_path)
        target_ref = self._resolve_target_ref(repository=repository, branch=branch)
        repository.git.worktree("add", "--force", "--detach", worktree_path.as_posix(), target_ref)
        return self._build_metadata(base_repo_path=base_repo_path, worktree_path=worktree_path, branch=branch)

    def _ensure_base_repo(self, *, owner: str, name: str, branch: str) -> Path:
        base_repo_path = self.get_base_repo_path(owner=owner, name=name)
        clone_url = f"https://github.com/{owner}/{name}.git"
        if self.settings.github_token:
            clone_url = f"https://{self.settings.github_token}:x-oauth-basic@github.com/{owner}/{name}.git"

        if not base_repo_path.exists():
            base_repo_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                git.Repo.clone_from(clone_url, base_repo_path.as_posix(), branch=branch, depth=1)
            except git.exc.GitCommandError:
                git.Repo.clone_from(clone_url, base_repo_path.as_posix(), depth=1)
            return base_repo_path

        try:
            repository = git.Repo(base_repo_path)
            repository.git.fetch("origin", branch, depth=1)
            default_branch = self._resolve_target_ref(repository=repository, branch=branch)
            if repository.head.is_detached:
                repository.git.checkout(default_branch)
            else:
                repository.git.checkout(branch)
                repository.git.pull("origin", branch)
        except Exception as exc:
            logger.warning("Failed to refresh repository base workspace: %s", exc)
        return base_repo_path

    def _resolve_target_ref(self, *, repository: git.Repo, branch: str) -> str:
        remote_ref_name = f"origin/{branch}"
        try:
            repository.commit(remote_ref_name)
            return remote_ref_name
        except Exception:
            pass

        try:
            repository.commit(branch)
            return branch
        except Exception:
            return repository.head.commit.hexsha

    def _build_metadata(self, *, base_repo_path: Path, worktree_path: Path, branch: str) -> dict[str, str]:
        return {
            "base_repo_path": base_repo_path.as_posix(),
            "worktree_path": worktree_path.as_posix(),
            "branch": branch,
        }
