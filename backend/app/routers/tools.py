from __future__ import annotations

from fastapi import APIRouter

from backend.app.services.tool_registry import list_api_tools


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
def list_tools() -> dict:
    return list_api_tools()
