from fastapi import HTTPException

from backend.app.routers import helpers
from backend.app.schemas import ChatAccepted, ChatAnswer, ChatRequest


def test_submit_chat_request_maps_missing_dialog_to_404(monkeypatch) -> None:
    def _missing_dialog(db, dialog_id: str, user_message: str):
        raise ValueError("dialog missing")

    monkeypatch.setattr(helpers, "submit_dialog_chat", _missing_dialog)

    try:
        helpers.submit_chat_request(db=object(), dialog_id="dialog_1", payload=ChatRequest(message="hello"))
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Dialog not found"


def test_submit_chat_request_masks_internal_error(monkeypatch) -> None:
    def _failing_submit(db, dialog_id: str, user_message: str):
        raise RuntimeError("secret backend failure")

    monkeypatch.setattr(helpers, "submit_dialog_chat", _failing_submit)

    try:
        helpers.submit_chat_request(db=object(), dialog_id="dialog_2", payload=ChatRequest(message="hello"))
        raise AssertionError("Expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail == "Chat submission failed"


def test_build_chat_response_event_supports_task_and_answer_modes() -> None:
    accepted_event = helpers.build_chat_response_event(
        dialog_id="dialog_1",
        response=ChatAccepted(task_id="task_1", dialog_id="dialog_1", status="queued"),
    )
    answer_event = helpers.build_chat_response_event(
        dialog_id="dialog_1",
        response=ChatAnswer(dialog_id="dialog_1", answer="done"),
    )

    assert accepted_event.type == "chat_accepted"
    assert accepted_event.task_id == "task_1"
    assert accepted_event.payload["response"]["mode"] == "task"
    assert answer_event.type == "chat_answer"
    assert answer_event.payload["response"]["mode"] == "answer"
