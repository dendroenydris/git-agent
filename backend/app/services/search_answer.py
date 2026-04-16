from __future__ import annotations

from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.entities import Dialog
from backend.app.rag.indexer import RepositoryIndexer


def answer_with_repository_context(*, db: Session, dialog: Dialog, user_message: str) -> str:
    if dialog.repository is None:
        return "This dialog has no repository linked, so RAG search cannot run."

    indexer = RepositoryIndexer()
    snapshot = indexer.ensure_index(
        db,
        owner=dialog.repository.owner,
        name=dialog.repository.name,
        branch=dialog.repository.branch,
    )
    db.flush()

    docs = []
    if snapshot.index.total_chunks > 0:
        docs = indexer.search(snapshot.index, user_message)

    context_blocks = indexer.format_context_blocks(
        docs,
        max_docs=6,
        max_chars_per_doc=1200,
    )

    if not context_blocks:
        summary = (
            snapshot.index.summary
            or dialog.repository.summary
            or "The repo is indexed, but nothing here matched your question."
        )
        return (
            "Retrieval did not return strong matches.\n"
            f"Repo summary: {summary}\n"
            "Try a narrower query: file path, symbol name, or exact error text."
        )

    settings = get_settings()
    if settings.openai_api_key:
        llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Answer using only the repository excerpts below. "
                    "If they are not enough, say what is missing. "
                    "Be brief; name files or symbols when you can.",
                ),
                (
                    "human",
                    "Question:\n{question}\n\nRepository context:\n{context}",
                ),
            ]
        )
        response = llm.invoke(
            prompt.format_messages(
                question=user_message,
                context="\n\n---\n\n".join(context_blocks),
            )
        )
        return str(response.content)

    preview = "\n\n".join(context_blocks[:3])
    return (
        "RAG retrieval is done. Closest excerpts:\n\n"
        f"{preview}\n\n"
        "OPENAI_API_KEY is unset, so this is raw context instead of a model summary."
    )
