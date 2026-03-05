from __future__ import annotations

import argparse
import logging
import os
import sys

from aiohttp import web

from .camera import CameraService
from .camera_protocol import CameraProtocol
from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub
from .mock_camera import MockCameraService
from .server import WebServer

log = logging.getLogger(__name__)


def _run(mock: bool = False) -> None:
    config = CameraConfig.from_env()
    host = os.environ.get("BASLER_HOST", "127.0.0.1")
    encoder = ImageEncoder()
    hub = FrameHub()
    camera: CameraProtocol
    if mock:
        log.info("Mock mode enabled — streaming synthetic test card")
        camera = MockCameraService(config, encoder, hub)
    else:
        camera = CameraService(config, encoder, hub)
    server = WebServer(config, camera, encoder, hub)

    app = server.build_app()
    log.info("Basler daemon listening on http://%s:%d  (viewer: /)", host, config.port)
    web.run_app(app, host=host, port=config.port)
    log.info("Daemon stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="basler-daemon", description="Basler camera daemon")
    sub = parser.add_subparsers(dest="command")
    run_parser = sub.add_parser("run", help="Run in the foreground (default)")
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="Use synthetic SMPTE test-card feed (no camera required)",
    )
    sub.add_parser("install", help="Register as an OS service with autostart")
    sub.add_parser("uninstall", help="Remove the OS service")
    sub.add_parser("start", help="Start the OS service")
    sub.add_parser("stop", help="Stop the OS service")

    args = parser.parse_args()

    if args.command is None or args.command == "run":
        _run(mock=getattr(args, "mock", False))
        return

    from . import service_manager

    commands = {
        "install": service_manager.install,
        "uninstall": service_manager.uninstall,
        "start": service_manager.start,
        "stop": service_manager.stop,
    }
    try:
        commands[args.command]()
    except Exception as exc:
        log.error("%s failed: %s", args.command, exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
