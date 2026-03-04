from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from basler_camera_daemon.hub import FrameHub


@pytest.fixture
def hub() -> FrameHub:
    return FrameHub()


def test_initial_client_count_is_zero(hub: FrameHub) -> None:
    assert hub.client_count() == 0


def test_add_increments_count(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.add(q)
    assert hub.client_count() == 1


def test_remove_decrements_count(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.remove(q)
    assert hub.client_count() == 0


def test_remove_nonexistent_does_not_raise(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.remove(q)  # must not raise
    assert hub.client_count() == 0


def test_broadcast_without_loop_does_not_raise(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast(b"frame")  # _loop is None — must not raise


def test_broadcast_uses_call_soon_threadsafe(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast(b"frame")
    mock_loop.call_soon_threadsafe.assert_called_once()


def test_broadcast_reaches_all_clients(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q1: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    q2: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
    hub.add(q1)
    hub.add(q2)
    hub.broadcast(b"frame")
    assert mock_loop.call_soon_threadsafe.call_count == 2
