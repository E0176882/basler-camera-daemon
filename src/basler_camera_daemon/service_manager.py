from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# ── macOS / launchd ───────────────────────────────────────────────────────────

_PLIST_LABEL = "com.basler.daemon"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"
_LOG_PATH = Path.home() / "Library" / "Logs" / "basler-daemon.log"


def _find_program_args() -> list[str]:
    exe = shutil.which("basler-daemon")
    if exe:
        return [exe, "run"]
    return [sys.executable, "-m", "basler_camera_daemon", "run"]


def _write_plist(program_args: list[str]) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    args_xml = "".join(f"        <string>{a}</string>\n" for a in program_args)
    content = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{_LOG_PATH}</string>
</dict>
</plist>
"""
    _PLIST_PATH.write_text(content, encoding="utf-8")


def _launchd_install() -> None:
    _write_plist(_find_program_args())
    subprocess.run(["launchctl", "load", str(_PLIST_PATH)], check=True)
    print(f"Installed: {_PLIST_PATH}")


def _launchd_uninstall() -> None:
    if _PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(_PLIST_PATH)], check=False)
        _PLIST_PATH.unlink()
    print("Service uninstalled.")


def _launchd_start() -> None:
    subprocess.run(["launchctl", "start", _PLIST_LABEL], check=True)
    print("Service started.")


def _launchd_stop() -> None:
    subprocess.run(["launchctl", "stop", _PLIST_LABEL], check=True)
    print("Service stopped.")


# ── Windows Service ───────────────────────────────────────────────────────────

_WIN_SVC_NAME = "BaslerDaemon"
_WIN_SVC_DISPLAY = "Basler Camera Daemon"
_WIN_SVC_DESC = "HTTP + WebSocket daemon for Basler cameras"

if sys.platform == "win32":
    import asyncio  # noqa: E402
    import logging  # noqa: E402
    import threading  # noqa: E402

    import win32service  # type: ignore[import-untyped]  # noqa: E402
    import win32serviceutil  # type: ignore[import-untyped]  # noqa: E402
    from aiohttp import web  # noqa: E402

    _win_log = logging.getLogger(__name__)

    class BaslerDaemonService(win32serviceutil.ServiceFramework):
        _svc_name_ = _WIN_SVC_NAME
        _svc_display_name_ = _WIN_SVC_DISPLAY
        _svc_description_ = _WIN_SVC_DESC

        def __init__(self, args: list[str]) -> None:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = threading.Event()

        def SvcStop(self) -> None:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop_event.set()

        def SvcDoRun(self) -> None:
            asyncio.run(self._async_main())

        async def _async_main(self) -> None:
            from .camera import CameraService
            from .config import CameraConfig
            from .encoding import ImageEncoder
            from .hub import FrameHub
            from .server import WebServer

            config = CameraConfig.from_env()
            host = "127.0.0.1"
            encoder = ImageEncoder()
            hub = FrameHub()
            camera = CameraService(config, encoder, hub)
            server = WebServer(config, camera, encoder, hub)
            app = server.build_app()

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host, config.port)
            await site.start()
            _win_log.info(
                "Basler daemon started as Windows service on http://%s:%d", host, config.port
            )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._stop_event.wait)

            _win_log.info("Windows service stopping...")
            await runner.cleanup()

    def _win_install() -> None:
        win32serviceutil.InstallService(
            f"{BaslerDaemonService.__module__}.{BaslerDaemonService.__qualname__}",
            _WIN_SVC_NAME,
            _WIN_SVC_DISPLAY,
            description=_WIN_SVC_DESC,
            startType=win32service.SERVICE_AUTO_START,
        )
        print(f"Service '{_WIN_SVC_NAME}' installed.")

    def _win_uninstall() -> None:
        win32serviceutil.RemoveService(_WIN_SVC_NAME)
        print(f"Service '{_WIN_SVC_NAME}' removed.")

    def _win_start() -> None:
        win32serviceutil.StartService(_WIN_SVC_NAME)
        print(f"Service '{_WIN_SVC_NAME}' started.")

    def _win_stop() -> None:
        win32serviceutil.StopService(_WIN_SVC_NAME)
        print(f"Service '{_WIN_SVC_NAME}' stopped.")


# ── public API ────────────────────────────────────────────────────────────────


def install() -> None:
    if sys.platform == "win32":
        _win_install()
    else:
        _launchd_install()


def uninstall() -> None:
    if sys.platform == "win32":
        _win_uninstall()
    else:
        _launchd_uninstall()


def start() -> None:
    if sys.platform == "win32":
        _win_start()
    else:
        _launchd_start()


def stop() -> None:
    if sys.platform == "win32":
        _win_stop()
    else:
        _launchd_stop()
