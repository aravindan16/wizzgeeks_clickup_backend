"""In-process WebSocket hub for pushing in-app notifications to connected users.

A module-level singleton (`hub`) tracks each user's open sockets, so the
notification service can push a payload to a recipient the moment a notification
is created. Single-process only — for multi-worker/multi-instance deployments
this would need a Redis (or similar) pub/sub fan-out behind the same interface.
"""
import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self) -> None:
        self._conns: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[user_id].add(ws)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(user_id)
            if conns:
                conns.discard(ws)
                if not conns:
                    self._conns.pop(user_id, None)

    async def push(self, user_id: str, payload: dict) -> None:
        """Send a JSON payload to all of a user's open sockets (best-effort)."""
        conns = list(self._conns.get(str(user_id), ()))
        if not conns:
            return
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 — a broken socket must not break the caller
                dead.append(ws)
        for ws in dead:
            await self.disconnect(str(user_id), ws)


# Process-wide singleton shared by the WS endpoint and the notification service.
hub = NotificationHub()
