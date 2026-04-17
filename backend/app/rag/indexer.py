from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import git
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.docstore.document import Document
from langchain_community.embeddings import FakeEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.entities import Repository, RepositoryIndex
from backend.app.services.dialogs import get_or_create_repository


logger = logging.getLogger(__name__)


@dataclass
class RepositorySnapshot:
    repository: Repository
    index: RepositoryIndex
    documents: list[Document]


class RepositoryIndexer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.supported_extensions = {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".env",
            ".sh",
            ".dockerfile",
            ".txt",
            ".sql",
        }
        self.supported_filenames = {
            "readme",
            "dockerfile",
            "makefile",
            "license",
            "copying",
            "requirements",
            "procfile",
            ".gitignore",
            ".dockerignore",
        }
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1400,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""],
        )
        self.critical_filenames = (
            "README",
            "README.md",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "requirements.txt",
            "pyproject.toml",
            "package.json",
            "Makefile",
        )

    def ensure_index(self, db: Session, *, owner: str, name: str, branch: str) -> RepositorySnapshot:
        repository = get_or_create_repository(db, owner=owner, name=name, branch=branch)
        existing = db.scalar(
            select(RepositoryIndex)
            .where(RepositoryIndex.repository_id == repository.id, RepositoryIndex.status == "completed")
            .order_by(desc(RepositoryIndex.updated_at))
        )
        has_vectorstore = existing and Path(existing.vectorstore_path).exists()
        has_useful_index = bool(existing and existing.total_files > 0)
        if has_vectorstore and has_useful_index:
            return RepositorySnapshot(repository=repository, index=existing, documents=[])

        return self.ingest_repository(db, owner=owner, name=name, branch=branch)

    def ingest_repository(self, db: Session, *, owner: str, name: str, branch: str) -> RepositorySnapshot:
        repository = get_or_create_repository(db, owner=owner, name=name, branch=branch)
        clone_dir = self._clone_repository(owner=owner, name=name, branch=branch)
        documents = self._load_documents(clone_dir)
        chunks = self.text_splitter.split_documents(documents)

        index = RepositoryIndex(
            repository_id=repository.id,
            status="running",
            vectorstore_path=str(self.settings.vectorstore_dir / repository.id),
            metadata_json={"owner": owner, "name": name, "branch": branch},
        )
        db.add(index)
        db.flush()

        persist_path = Path(index.vectorstore_path)
        persist_path.mkdir(parents=True, exist_ok=True)
        if chunks:
            embedding = self._embedding_model()
            vector_store = Chroma.from_documents(
                documents=chunks,
                embedding=embedding,
                persist_directory=str(persist_path),
            )
            vector_store.persist()

        summary = self._build_repository_summary(documents)
        index.status = "completed"
        index.total_files = len(documents)
        index.total_chunks = len(chunks)
        index.summary = summary
        index.metadata_json = {
            **index.metadata_json,
            "indexed_at": datetime.utcnow().isoformat(),
            "key_files": [document.metadata["source"] for document in documents[:50]],
            "extensions": sorted({document.metadata["extension"] for document in documents}),
        }

        repository.summary = summary
        repository.last_indexed_at = datetime.utcnow()
        repository.updated_at = datetime.utcnow()
        db.add(repository)
        db.add(index)
        db.flush()

        shutil.rmtree(clone_dir, ignore_errors=True)
        return RepositorySnapshot(repository=repository, index=index, documents=documents)

    def search(self, index: RepositoryIndex, query: str) -> list[Document]:
        if not Path(index.vectorstore_path).exists():
            return []

        try:
            vector_store = Chroma(
                persist_directory=index.vectorstore_path,
                embedding_function=self._embedding_model(),
            )
            return vector_store.similarity_search(query, k=6)
        except Exception:
            logger.exception("Repository search failed for index %s", index.id)
            return []

    def format_context_blocks(
        self,
        documents: list[Document],
        *,
        max_docs: int = 6,
        max_chars_per_doc: int = 1200,
    ) -> list[str]:
        blocks: list[str] = []
        for document in documents[:max_docs]:
            source = document.metadata.get("source", "unknown")
            content = (document.page_content or "")[:max_chars_per_doc]
            blocks.append(f"[{source}]\n{content}")
        return blocks

    def build_planner_context(
        self,
        db: Session,
        *,
        owner: str,
        name: str,
        branch: str,
        query: str,
    ) -> dict[str, Any]:
        snapshot = self.ensure_index(db, owner=owner, name=name, branch=branch)
        metadata = snapshot.index.metadata_json or {}
        key_files = list(metadata.get("key_files", []))
        extensions = list(metadata.get("extensions", []))

        docs: list[Document] = []
        if snapshot.index.total_chunks > 0 and query.strip():
            docs = self.search(snapshot.index, query)

        retrieved_context = [
            {
                "source": document.metadata.get("source", "unknown"),
                "content": (document.page_content or "")[:1200],
            }
            for document in docs[:6]
        ]
        critical_file_previews = self._load_critical_file_previews(
            owner=owner,
            name=name,
            branch=branch,
            max_chars_per_file=1200,
        )

        return {
            "repository_summary": snapshot.index.summary or snapshot.repository.summary or "",
            "key_files": key_files[:40],
            "extensions": extensions[:20],
            "total_files": snapshot.index.total_files,
            "total_chunks": snapshot.index.total_chunks,
            "retrieved_context": retrieved_context,
            "critical_file_previews": critical_file_previews,
        }

    def _embedding_model(self):
        if self.settings.has_usable_openai_api_key:
            return OpenAIEmbeddings(api_key=self.settings.openai_api_key)
        return FakeEmbeddings(size=1536)

    def _clone_repository(self, *, owner: str, name: str, branch: str) -> str:
        destination = tempfile.mkdtemp(prefix=f"git_rag_{owner}_{name}_")
        clone_url = f"https://github.com/{owner}/{name}.git"
        if self.settings.github_token:
            clone_url = f"https://{self.settings.github_token}:x-oauth-basic@github.com/{owner}/{name}.git"

        try:
            git.Repo.clone_from(clone_url, destination, branch=branch, depth=1)
        except git.exc.GitCommandError:
            # Some repositories still use non-main defaults (for example `master`).
            git.Repo.clone_from(clone_url, destination, depth=1)
        return destination

    def _load_documents(self, repo_path: str) -> list[Document]:
        root = Path(repo_path)
        documents: list[Document] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part.startswith(".") for part in file_path.parts):
                continue
            filename = file_path.name
            stem = file_path.stem.lower()
            suffix = file_path.suffix.lower()
            has_supported_extension = suffix in self.supported_extensions
            is_supported_filename = filename.lower() in self.supported_filenames or stem in self.supported_filenames
            if not has_supported_extension and not is_supported_filename:
                continue
            if "node_modules" in file_path.parts or "__pycache__" in file_path.parts:
                continue

            content = file_path.read_text(encoding="utf-8", errors="ignore")
            relative = file_path.relative_to(root)
            documents.append(
                Document(
                    page_content=content,
                    metadata={
                        "source": str(relative),
                        "filename": filename,
                        "extension": suffix if suffix else "none",
                    },
                )
            )
        return documents

    def _build_repository_summary(self, documents: list[Document]) -> str:
        file_names = [document.metadata["filename"] for document in documents]
        languages = sorted({document.metadata["extension"] for document in documents})
        return (
            f"Indexed {len(documents)} files. "
            f"Primary file types: {', '.join(languages[:8])}. "
            f"Key files: {', '.join(file_names[:10])}."
        )

    def _load_critical_file_previews(
        self,
        *,
        owner: str,
        name: str,
        branch: str,
        max_chars_per_file: int,
    ) -> list[dict[str, str]]:
        workspace_path = self.settings.repo_cache_dir / f"{owner}__{name}"
        cleanup_path: Path | None = None
        if not workspace_path.exists():
            cleanup_path = Path(self._clone_repository(owner=owner, name=name, branch=branch))
            workspace_path = cleanup_path

        previews: list[dict[str, str]] = []
        seen_sources: set[str] = set()
        for file_path in workspace_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name not in self.critical_filenames:
                continue
            relative_path = file_path.relative_to(workspace_path).as_posix()
            if relative_path in seen_sources:
                continue
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            previews.append(
                {
                    "source": relative_path,
                    "content": content[:max_chars_per_file],
                }
            )
            seen_sources.add(relative_path)
            if len(previews) >= 8:
                break

        if cleanup_path is not None:
            shutil.rmtree(cleanup_path.as_posix(), ignore_errors=True)
        return previews
