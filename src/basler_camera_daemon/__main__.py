from __future__ import annotations

import logging
import os

from aiohttp import web

from .camera import CameraService
from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub
from .server import WebServer

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = CameraConfig.from_env()
    host = os.environ.get("BASLER_HOST", "127.0.0.1")
    encoder = ImageEncoder()
    hub = FrameHub()
    camera = CameraService(config, encoder, hub)
    server = WebServer(config, camera, encoder, hub)

    app = server.build_app()
    log.info("Basler daemon listening on http://%s:%d  (viewer: /)", host, config.port)
    web.run_app(app, host=host, port=config.port)
    log.info("Daemon stopped")


if __name__ == "__main__":
    main()
