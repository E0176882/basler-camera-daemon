from __future__ import annotations

import asyncio
import contextlib
import threading


class FrameHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[asyncio.Queue[bytes | str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Store the running event loop. Call once from the asyncio startup handler
        before the camera thread starts broadcasting."""
        self._loop = loop

    def add(self, queue: asyncio.Queue[bytes | str]) -> None:
        with self._lock:
            self._clients.add(queue)

    def remove(self, queue: asyncio.Queue[bytes | str]) -> None:
        with self._lock:
            self._clients.discard(queue)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, frame: bytes) -> None:
        """Fan-out frame bytes to all subscribers. Safe to call from any thread."""
        self._broadcast_item(frame)

    def broadcast_status(self, connected: bool) -> None:
        """Fan-out a JSON status message to all subscribers. Safe to call from any thread."""
        msg = (
            '{"type":"status","connected":true}'
            if connected
            else '{"type":"status","connected":false}'
        )
        self._broadcast_item(msg)

    def _broadcast_item(self, item: bytes | str) -> None:
        if self._loop is None:
            return
        with self._lock:
            clients = list(self._clients)
        for q in clients:

            def _put(q: asyncio.Queue[bytes | str] = q, item: bytes | str = item) -> None:
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(item)

            self._loop.call_soon_threadsafe(_put)
