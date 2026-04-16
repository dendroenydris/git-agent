from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from backend.app.core.config import get_settings
from backend.app.schemas import TaskEvent


logger = logging.getLogger(__name__)
settings = get_settings()
EVENT_CHANNEL = "agentic_rag.events"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, dialog_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[dialog_id].add(websocket)

    def disconnect(self, dialog_id: str, websocket: WebSocket) -> None:
        if dialog_id not in self._connections:
            return

        self._connections[dialog_id].discard(websocket)
        if not self._connections[dialog_id]:
            self._connections.pop(dialog_id, None)

    async def broadcast_dialog_event(self, dialog_id: str, event: TaskEvent) -> None:
        dead_connections: list[WebSocket] = []
        for connection in self._connections.get(dialog_id, set()):
            try:
                await connection.send_text(event.model_dump_json())
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(dialog_id, connection)


manager = ConnectionManager()


class RedisEventSubscriber:
    def __init__(self) -> None:
        self._client: AsyncRedis | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return

        self._client = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
        self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _listen(self) -> None:
        assert self._client is not None
        try:
            pubsub = self._client.pubsub()
            await pubsub.subscribe(EVENT_CHANNEL)
            async for raw_message in pubsub.listen():
                if raw_message.get("type") != "message":
                    continue

                try:
                    payload = json.loads(raw_message["data"])
                    event = TaskEvent.model_validate(payload)
                    if event.dialog_id:
                        await manager.broadcast_dialog_event(event.dialog_id, event)
                except Exception as exc:
                    logger.warning("Failed to process Redis event: %s", exc)
        except Exception as exc:
            logger.warning("Redis subscriber unavailable: %s", exc)


subscriber = RedisEventSubscriber()


def publish_event(event: TaskEvent) -> None:
    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        client.publish(EVENT_CHANNEL, event.model_dump_json())
        client.close()
    except Exception as exc:
        logger.warning("Failed to publish Redis event: %s", exc)
