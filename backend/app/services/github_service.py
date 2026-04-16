from __future__ import annotations

import base64
from dataclasses import dataclass
import logging

from github import Github
from github.Repository import Repository as GitHubRepository

from backend.app.core.config import get_settings


logger = logging.getLogger(__name__)


@dataclass
class GitHubContext:
    owner: str
    name: str
    branch: str = "main"
    token: str | None = None


class GitHubService:
    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        self._token = token or settings.github_token
        self._client = Github(login_or_token=self._token) if self._token else None

    def _repo(self, context: GitHubContext) -> GitHubRepository:
        if self._client is None:
            raise ValueError("GitHub token is required for PAT-backed automation")

        return self._client.get_repo(f"{context.owner}/{context.name}")

    def get_repository_metadata(self, context: GitHubContext) -> dict:
        repository = self._repo(context)
        return {
            "full_name": repository.full_name,
            "default_branch": repository.default_branch,
            "description": repository.description,
            "private": repository.private,
            "language": repository.language,
            "open_issues_count": repository.open_issues_count,
        }

    def create_issue_comment(self, context: GitHubContext, *, issue_number: int, body: str) -> dict:
        repository = self._repo(context)
        issue = repository.get_issue(number=issue_number)
        comment = issue.create_comment(body)
        return {
            "issue_number": issue_number,
            "comment_id": comment.id,
            "html_url": comment.html_url,
            "body": body,
        }

    def dispatch_workflow(
        self,
        context: GitHubContext,
        *,
        workflow_id: str,
        ref: str | None = None,
        inputs: dict | None = None,
    ) -> dict:
        repository = self._repo(context)
        workflow = repository.get_workflow(workflow_id)
        dispatched = workflow.create_dispatch(ref=ref or context.branch, inputs=inputs or {})
        return {
            "workflow_id": workflow_id,
            "ref": ref or context.branch,
            "accepted": bool(dispatched),
        }

    def create_pull_request(
        self,
        context: GitHubContext,
        *,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> dict:
        repository = self._repo(context)
        pull_request = repository.create_pull(
            title=title,
            body=body,
            head=head,
            base=base or context.branch,
        )
        return {
            "number": pull_request.number,
            "html_url": pull_request.html_url,
            "title": pull_request.title,
        }

    def commit_file(
        self,
        context: GitHubContext,
        *,
        path: str,
        message: str,
        content: str,
        branch: str,
    ) -> dict:
        repository = self._repo(context)
        encoded_content = content.encode("utf-8")
        try:
            existing = repository.get_contents(path, ref=branch)
            update = repository.update_file(
                path=path,
                message=message,
                content=encoded_content,
                sha=existing.sha,
                branch=branch,
            )
            return {
                "path": path,
                "branch": branch,
                "commit_sha": update["commit"].sha,
                "created": False,
            }
        except Exception:
            create = repository.create_file(
                path=path,
                message=message,
                content=base64.b64decode(base64.b64encode(encoded_content)).decode("utf-8"),
                branch=branch,
            )
            return {
                "path": path,
                "branch": branch,
                "commit_sha": create["commit"].sha,
                "created": True,
            }
