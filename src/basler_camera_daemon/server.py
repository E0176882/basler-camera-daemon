from __future__ import annotations

import asyncio
import base64
import importlib.resources
import logging

from aiohttp import ClientConnectionResetError, web

from .camera import CameraService
from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

log = logging.getLogger(__name__)


class WebServer:
    def __init__(
        self,
        config: CameraConfig,
        camera: CameraService,
        encoder: ImageEncoder,
        hub: FrameHub,
    ) -> None:
        self._config = config
        self._camera = camera
        self._encoder = encoder
        self._hub = hub
        self._viewer_html = self._load_viewer()

    def _load_viewer(self) -> str:
        pkg = importlib.resources.files("basler_camera_daemon")
        return (pkg / "static" / "viewer.html").read_text(encoding="utf-8")

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._handle_viewer)
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/stream", self._handle_stream)
        app.router.add_post("/capture", self._handle_capture)
        app.on_startup.append(self._on_startup)
        app.on_shutdown.append(self._on_shutdown)
        return app

    async def _on_startup(self, app: web.Application) -> None:
        self._hub.set_loop(asyncio.get_running_loop())
        self._camera.start()

    async def _on_shutdown(self, app: web.Application) -> None:
        log.info("Server shutting down, stopping camera…")
        await asyncio.get_running_loop().run_in_executor(None, self._camera.stop)

    async def _handle_viewer(self, request: web.Request) -> web.Response:
        return web.Response(text=self._viewer_html, content_type="text/html", charset="utf-8")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "model": self._camera.model_name})

    async def _handle_stream(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
        self._hub.add(q)
        log.info("WS client connected (%d total)", self._hub.client_count())
        try:
            while not ws.closed:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=5.0)
                    if isinstance(item, bytes):
                        await ws.send_bytes(item)
                    else:
                        await ws.send_str(item)
                except TimeoutError:
                    pass
                except (asyncio.CancelledError, ClientConnectionResetError):
                    break
        finally:
            self._hub.remove(q)
            log.info("WS client disconnected (%d remaining)", self._hub.client_count())

        return ws

    async def _handle_capture(self, request: web.Request) -> web.Response:
        arr = self._camera.get_latest_raw()
        if arr is None:
            return web.json_response({"error": "no frame available"}, status=503)

        jpeg = self._encoder.encode(arr, self._config.capture_quality)
        encoded = base64.b64encode(jpeg).decode()
        return web.json_response({"image_base64": encoded})
