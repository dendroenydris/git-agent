from types import SimpleNamespace

from backend.app.workers import jobs


class _FakeDb:
    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_process_task_prefers_langgraph_runner(monkeypatch) -> None:
    fake_db = _FakeDb()
    captured: dict[str, bool] = {"graph_called": False, "orchestrator_called": False}

    class _FakeGraphRunner:
        def __init__(self, db) -> None:
            assert db is fake_db

        def process_task(self, task_id: str):
            captured["graph_called"] = True
            assert task_id == "task_1"
            return {"runner": "graph"}

    class _FakeOrchestrator:
        def __init__(self, db) -> None:
            assert db is fake_db

        def process_task(self, task_id: str):
            captured["orchestrator_called"] = True
            return {"runner": "orchestrator"}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(jobs, "LangGraphRunner", _FakeGraphRunner)
    monkeypatch.setattr(jobs, "AgentOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(jobs.settings, "graph_runner_enabled", True)

    result = jobs.process_task("task_1")

    assert result == {"runner": "graph"}
    assert captured["graph_called"] is True
    assert captured["orchestrator_called"] is False


def test_process_task_falls_back_to_orchestrator(monkeypatch) -> None:
    fake_db = _FakeDb()
    captured: dict[str, bool] = {"graph_called": False, "orchestrator_called": False}

    class _FailingGraphRunner:
        def __init__(self, db) -> None:
            assert db is fake_db

        def process_task(self, task_id: str):
            captured["graph_called"] = True
            raise RuntimeError("graph failed")

    class _FakeOrchestrator:
        def __init__(self, db) -> None:
            assert db is fake_db

        def process_task(self, task_id: str):
            captured["orchestrator_called"] = True
            return {"runner": "orchestrator"}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(jobs, "LangGraphRunner", _FailingGraphRunner)
    monkeypatch.setattr(jobs, "AgentOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(jobs.settings, "graph_runner_enabled", True)

    result = jobs.process_task("task_2")

    assert result == {"runner": "orchestrator"}
    assert captured["graph_called"] is True
    assert captured["orchestrator_called"] is True

