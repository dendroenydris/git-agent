from __future__ import annotations

import json
from typing import Literal

from langchain.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.app.core.config import get_settings


RouteMode = Literal["answer", "task"]


AUTOMATION_HINTS = {
    "run",
    "install",
    "setup",
    "deploy",
    "docker",
    "build",
    "execute",
    "trigger",
    "workflow",
    "create",
    "modify",
    "fix",
    "comment",
    "pr",
    "pull request",
    "issue",
    "test",
    "pytest",
}


def decide_route_mode(message: str) -> RouteMode:
    settings = get_settings()
    if settings.has_usable_openai_api_key:
        try:
            return _llm_decide_mode(message=message, model=settings.openai_model, api_key=settings.openai_api_key)
        except Exception:
            pass
    return _heuristic_decide_mode(message)


def _heuristic_decide_mode(message: str) -> RouteMode:
    lowered = message.lower().strip()
    if not lowered:
        return "answer"

    if "?" in lowered and not any(token in lowered for token in AUTOMATION_HINTS):
        return "answer"

    if any(token in lowered for token in AUTOMATION_HINTS):
        return "task"

    return "answer"


def _llm_decide_mode(*, message: str, model: str, api_key: str) -> RouteMode:
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You route user intent for a DevOps copilot. "
                "Return strict JSON only: {{\"mode\":\"answer\"|\"task\"}}. "
                "Use task for workflows that execute tools, shell, docker, git, CI/CD, or repo mutations. "
                "Use answer for explanation/search/Q&A.",
            ),
            ("human", "{message}"),
        ]
    )
    response = llm.invoke(prompt.format_messages(message=message))
    try:
        parsed = json.loads(str(response.content))
        mode = parsed.get("mode")
        if mode in {"answer", "task"}:
            return mode
    except Exception:
        pass
    return _heuristic_decide_mode(message)
