from functools import lru_cache
import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "AI DevOps Copilot API"
    api_prefix: str = "/api"
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/git_rag",
        )
    )
    redis_url: str = Field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model: str = Field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    )
    github_token: str | None = Field(default_factory=lambda: os.getenv("GITHUB_TOKEN"))
    repo_cache_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("REPO_CACHE_DIR", "./backend/.data/repositories")
        ).resolve()
    )
    vectorstore_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("VECTORSTORE_DIR", "./backend/.data/vectorstores")
        ).resolve()
    )
    execution_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "900"))
    )
    graph_runner_enabled: bool = Field(
        default_factory=lambda: os.getenv("GRAPH_RUNNER_ENABLED", "true").lower() == "true"
    )
    command_allowlist: list[str] = Field(
        default_factory=lambda: [
            "python",
            "python3",
            "pip",
            "pip3",
            "pytest",
            "npm",
            "node",
            "yarn",
            "pnpm",
            "docker",
            "git",
            "bash",
            "sh",
            "ls",
            "cat",
            "rg",
            "sed",
            "head",
            "tail",
            "pwd",
            "echo",
        ]
    )
    dangerous_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "shutdown",
            "reboot",
            "mkfs",
            "dd ",
            ":(){:|:&};:",
        ]
    )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def has_usable_openai_api_key(self) -> bool:
        api_key = (self.openai_api_key or "").strip()
        if not api_key:
            return False

        placeholder_values = {
            "your_openai_api_key_here",
            "sk-your-openai-api-key-here",
            "replace_me",
        }
        if api_key in placeholder_values:
            return False
        if api_key.startswith("your_"):
            return False
        return True


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.repo_cache_dir.mkdir(parents=True, exist_ok=True)
    settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    return settings
