from sqlalchemy import desc, select

from backend.app.db.session import SessionLocal
from backend.app.models.entities import RepositoryIndex
from backend.app.rag.indexer import RepositoryIndexer


class RAGPipeline:
    def __init__(self) -> None:
        self.indexer = RepositoryIndexer()

    async def analyze_repository(self, repo_data: dict, task_id: str) -> dict:
        del task_id
        db = SessionLocal()
        try:
            snapshot = self.indexer.ingest_repository(
                db,
                owner=repo_data["owner"],
                name=repo_data["name"],
                branch=repo_data.get("branch", "main"),
            )
            db.commit()
            return {
                "repository": repo_data,
                "vectorstore_id": snapshot.index.id,
                "total_files": snapshot.index.total_files,
                "total_chunks": snapshot.index.total_chunks,
                "summary": snapshot.index.summary,
            }
        finally:
            db.close()

    async def search_repository(self, task_id: str, query: str, repo_metadata: dict):
        del task_id
        db = SessionLocal()
        try:
            statement = (
                select(RepositoryIndex)
                .join(RepositoryIndex.repository)
                .where(
                    RepositoryIndex.metadata_json["owner"].as_string() == repo_metadata["owner"],
                    RepositoryIndex.metadata_json["name"].as_string() == repo_metadata["name"],
                )
                .order_by(desc(RepositoryIndex.updated_at))
            )
            index = db.scalar(statement)
            if index is None:
                return []
            return self.indexer.search(index, query)
        finally:
            db.close()