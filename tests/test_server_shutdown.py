from __future__ import annotations

import threading
from typing import Any, cast

import numpy as np
from aiohttp import web

from basler_camera_daemon.camera_protocol import CameraProtocol
from basler_camera_daemon.config import CameraConfig
from basler_camera_daemon.encoding import ImageEncoder
from basler_camera_daemon.hub import FrameHub
from basler_camera_daemon.server import WebServer


class _DummyCamera(CameraProtocol):
    def __init__(self) -> None:
        self.stop_called = threading.Event()

    @property
    def model_name(self) -> str:
        return "dummy"

    @property
    def is_connected(self) -> bool:
        return False

    def get_latest_raw(self) -> np.ndarray[Any, np.dtype[Any]] | None:
        return None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_called.set()


class _FakeWs:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.close_calls = 0
        self.should_fail = should_fail

    async def close(self) -> None:
        self.close_calls += 1
        if self.should_fail:
            raise RuntimeError("close failed")


async def test_on_shutdown_closes_ws_clients_and_stops_camera() -> None:
    camera = _DummyCamera()
    server = WebServer(CameraConfig(), camera, ImageEncoder(), FrameHub())
    ws1 = _FakeWs()
    ws2 = _FakeWs()
    server._ws_clients.add(cast(web.WebSocketResponse, ws1))
    server._ws_clients.add(cast(web.WebSocketResponse, ws2))

    await server._on_shutdown(web.Application())

    assert ws1.close_calls == 1
    assert ws2.close_calls == 1
    assert camera.stop_called.is_set()
    assert server._ws_clients == set()


async def test_close_all_stream_clients_suppresses_ws_close_errors() -> None:
    server = WebServer(CameraConfig(), _DummyCamera(), ImageEncoder(), FrameHub())
    bad_ws = _FakeWs(should_fail=True)
    good_ws = _FakeWs()
    server._ws_clients.add(cast(web.WebSocketResponse, bad_ws))
    server._ws_clients.add(cast(web.WebSocketResponse, good_ws))

    await server._close_all_stream_clients()

    assert bad_ws.close_calls == 1
    assert good_ws.close_calls == 1
    assert server._ws_clients == set()
