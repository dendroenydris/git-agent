from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.entities import Dialog, Message, Repository, TaskRun
from backend.app.models.enums import MessageType
from backend.app.schemas import AgentMessageRead, DialogRead, RepositoryRef


def get_or_create_repository(
    db: Session,
    *,
    owner: str,
    name: str,
    branch: str,
) -> Repository:
    statement = select(Repository).where(
        Repository.owner == owner,
        Repository.name == name,
        Repository.branch == branch,
    )
    repository = db.scalar(statement)
    if repository:
        return repository

    repository = Repository(owner=owner, name=name, branch=branch)
    db.add(repository)
    db.flush()
    return repository


def create_dialog(db: Session, *, owner: str, name: str, branch: str) -> Dialog:
    repository = get_or_create_repository(db, owner=owner, name=name, branch=branch)
    dialog = Dialog(
        title=f"{owner}/{name}",
        repository_id=repository.id,
    )
    db.add(dialog)
    db.flush()
    return dialog


def list_dialogs(db: Session) -> list[Dialog]:
    statement = (
        select(Dialog)
        .options(selectinload(Dialog.messages), selectinload(Dialog.repository))
        .order_by(desc(Dialog.updated_at))
    )
    return list(db.scalars(statement).unique())


def get_dialog(db: Session, dialog_id: str) -> Dialog | None:
    statement = (
        select(Dialog)
        .where(Dialog.id == dialog_id)
        .options(
            selectinload(Dialog.messages),
            selectinload(Dialog.repository),
            selectinload(Dialog.tasks).selectinload(TaskRun.steps),
        )
    )
    return db.scalar(statement)


def add_message(
    db: Session,
    *,
    dialog_id: str,
    content: str,
    message_type: MessageType,
    task_id: str | None = None,
    summary: str | None = None,
    metadata: dict | None = None,
) -> Message:
    message = Message(
        dialog_id=dialog_id,
        content=content,
        type=message_type,
        task_id=task_id,
        summary=summary,
        metadata_json=metadata or {},
    )
    db.add(message)
    db.flush()
    return message


def dialog_to_read(dialog: Dialog) -> DialogRead:
    repo = None
    if dialog.repository:
        repo = RepositoryRef(
            owner=dialog.repository.owner,
            name=dialog.repository.name,
            branch=dialog.repository.branch,
        )

    messages = [AgentMessageRead.model_validate(message) for message in dialog.messages]
    return DialogRead(
        id=dialog.id,
        title=dialog.title,
        created_at=dialog.created_at,
        updated_at=dialog.updated_at,
        repo=repo,
        messages=messages,
    )
