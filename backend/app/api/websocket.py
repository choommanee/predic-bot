"""
WebSocket manager — broadcasts real-time trading events to all connected clients.
"""
from __future__ import annotations
import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)
        logger.info("WS connected. Total: %d", len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)
        logger.info("WS disconnected. Total: %d", len(self._active))

    async def broadcast(self, data: dict) -> None:
        if not self._active:
            return
        message = json.dumps(data, default=str)
        dead: Set[WebSocket] = set()
        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._active -= dead


manager = ConnectionManager()
