"""In-process events and the visualiser's event stream."""

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

EVENT_TYPES: tuple[str, ...] = (
    "doc.changed",
    "job.started",
    "job.progress",
    "job.finished",
    "section.state",
    "section.attempt",
    "look.progress",
    "build.finished",
    "learning.proposed",
    "queue.changed",
)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=1000)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, type: str, data: dict[str, Any]) -> None:
        if type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {type}")
        event = {"type": type, "data": data}
        for queue in self._subscribers:
            queue.put_nowait(event)
        self._history.append(event)

    def recent(self) -> list[dict[str, Any]]:
        return list(self._history)

    def subscriber_count(self) -> int:
        return len(self._subscribers)


router = APIRouter()


async def _stream(request: Request) -> AsyncIterator[str]:
    bus: EventBus = request.app.state.bus
    queue = bus.subscribe()
    try:
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=request.app.state.keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
            else:
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
    finally:
        bus.unsubscribe(queue)


@router.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(_stream(request), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
