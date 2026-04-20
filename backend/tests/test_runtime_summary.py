from backend.app.agents.runtime import AgentRuntime


def _build_runtime() -> AgentRuntime:
    runtime = AgentRuntime.__new__(AgentRuntime)
    runtime.llm = None
    return runtime


def test_build_summary_uses_digest_instead_of_raw_terminal_output() -> None:
    runtime = _build_runtime()
    long_output = "\n".join(
        [
            "$ pytest",
            "============================= test session starts =============================",
            "collected 12 items",
            "tests/test_app.py ....",
            "tests/test_api.py ....",
            "12 passed in 4.21s",
        ]
    )

    summary = runtime.build_summary(
        user_message="run the test suite",
        completion_summary="Tests completed successfully.",
        results=[
            {
                "step": "Run tests",
                "success": True,
                "output": long_output,
            }
        ],
    )

    assert "Outcome: Tests completed successfully." in summary
    assert "12 passed in 4.21s" in summary
    assert "============================= test session starts" not in summary
    assert "$ pytest" not in summary


def test_summary_digest_prefers_error_text_and_truncates_long_lines() -> None:
    runtime = _build_runtime()
    digest = runtime._build_summary_result_digest(
        [
            {
                "step": "Run migration",
                "success": False,
                "output": "stdout line that should not win",
                "error": "Database connection failed because the credentials were rejected by the server after retrying multiple times.",
            }
        ]
    )

    step = digest["steps"][0]
    assert step["success"] is False
    assert step["step"] == "Run migration"
    assert "credentials were rejected" in step["outcome"]
    assert len(step["outcome"]) <= 120
