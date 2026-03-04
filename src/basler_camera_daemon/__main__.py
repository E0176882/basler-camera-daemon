from __future__ import annotations

import logging

from aiohttp import web

from .camera import CameraService
from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub
from .server import WebServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def main() -> None:
    config = CameraConfig.from_env()
    encoder = ImageEncoder()
    hub = FrameHub()
    camera = CameraService(config, encoder, hub)
    server = WebServer(config, camera, encoder, hub)

    app = server.build_app()
    log.info("Basler daemon listening on http://127.0.0.1:%d  (viewer: /)", config.port)
    web.run_app(app, host="127.0.0.1", port=config.port)
    log.info("Daemon stopped")


if __name__ == "__main__":
    main()
