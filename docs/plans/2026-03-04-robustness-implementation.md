# Robustness & OS Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add camera reconnection with viewer status overlay, and OS service registration (launchd on macOS, Windows Service via pywin32) with a CLI subcommand dispatcher.

**Architecture:** `CameraService._grab_loop` gains an outer retry loop with exponential backoff; `FrameHub` broadcasts JSON status messages to all WebSocket clients; a new `service_manager.py` handles platform-specific service registration; `__main__.py` becomes an `argparse` dispatcher.

**Tech Stack:** Python 3.13, aiohttp, pypylon, pywin32 (Windows only), launchctl (macOS), argparse

---

## Context

Design doc: `docs/plans/2026-03-04-robustness-design.md`

Current package layout:
```
src/basler_camera_daemon/
    __init__.py
    __main__.py      ← add argparse CLI
    config.py
    encoding.py
    hub.py           ← add broadcast_status, change queue type
    camera.py        ← add outer retry loop + is_connected
    server.py        ← handle bytes|str in stream handler
    static/
        viewer.html  ← add disconnect overlay
tests/
    test_hub.py      ← update queue types, add broadcast_status tests
```

Run all checks with:
```bash
ruff check src tests && ruff format --check src tests && mypy src && pytest -v
```

---

### Task 1: `hub.py` — queue type + `broadcast_status`

**Files:**
- Modify: `src/basler_camera_daemon/hub.py`
- Modify: `tests/test_hub.py`

**Step 1: Add the failing tests**

Replace `tests/test_hub.py` entirely with:

```python
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
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    assert hub.client_count() == 1


def test_remove_decrements_count(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.remove(q)
    assert hub.client_count() == 0


def test_remove_nonexistent_does_not_raise(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.remove(q)  # must not raise
    assert hub.client_count() == 0


def test_broadcast_without_loop_does_not_raise(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast(b"frame")  # _loop is None — must not raise


def test_broadcast_uses_call_soon_threadsafe(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast(b"frame")
    mock_loop.call_soon_threadsafe.assert_called_once()


def test_broadcast_reaches_all_clients(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q1: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    q2: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q1)
    hub.add(q2)
    hub.broadcast(b"frame")
    assert mock_loop.call_soon_threadsafe.call_count == 2


def test_broadcast_status_without_loop_does_not_raise(hub: FrameHub) -> None:
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast_status(False)  # _loop is None — must not raise


def test_broadcast_status_uses_call_soon_threadsafe(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q)
    hub.broadcast_status(True)
    mock_loop.call_soon_threadsafe.assert_called_once()


def test_broadcast_status_reaches_all_clients(hub: FrameHub) -> None:
    mock_loop = MagicMock()
    hub.set_loop(mock_loop)
    q1: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    q2: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
    hub.add(q1)
    hub.add(q2)
    hub.broadcast_status(False)
    assert mock_loop.call_soon_threadsafe.call_count == 2
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_hub.py -v
```

Expected: FAIL — `FrameHub` has no `broadcast_status` method and queue type mismatch.

**Step 3: Replace `src/basler_camera_daemon/hub.py` entirely**

```python
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
```

**Step 4: Run tests**

```bash
pytest tests/test_hub.py -v
```

Expected: all 10 tests PASS.

**Step 5: Lint and type-check**

```bash
ruff check src/basler_camera_daemon/hub.py tests/test_hub.py
ruff format --check src/basler_camera_daemon/hub.py tests/test_hub.py
mypy src
```

Fix any issues reported. Common fix: `ruff format src/basler_camera_daemon/hub.py tests/test_hub.py`

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/hub.py tests/test_hub.py
git commit -m "feat: add broadcast_status to FrameHub; queue type bytes|str"
```

---

### Task 2: `camera.py` — outer retry loop + `is_connected`

**Files:**
- Modify: `src/basler_camera_daemon/camera.py`

No new unit tests — `CameraService` requires hardware. Existing tests must still pass.

**Step 1: Replace `src/basler_camera_daemon/camera.py` entirely**

```python
from __future__ import annotations

import logging
import threading

import numpy as np
from pypylon import pylon  # type: ignore[import-untyped, unused-ignore]

from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

log = logging.getLogger(__name__)

# The converter always outputs RGB8packed. For Mono8 cameras this replicates
# the single channel into all three, producing a (H, W, 3) array.
_PIXEL_FORMAT_PREFERENCE = ["BayerRG8", "BayerGB8", "BayerGR8", "BayerBG8", "RGB8", "BGR8", "Mono8"]


class CameraService:
    def __init__(
        self,
        config: CameraConfig,
        encoder: ImageEncoder,
        hub: FrameHub,
    ) -> None:
        self._config = config
        self._encoder = encoder
        self._hub = hub
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._raw_lock = threading.Lock()
        self._model_name = "unknown"
        self._latest_raw: np.ndarray | None = None
        self._connected = False

    @property
    def model_name(self) -> str:
        with self._raw_lock:
            return self._model_name

    @property
    def is_connected(self) -> bool:
        with self._raw_lock:
            return self._connected

    def get_latest_raw(self) -> np.ndarray | None:
        # Returns a copy of the most recently grabbed frame.
        # The copy is owned by Python; callers may read it safely after this call returns.
        with self._raw_lock:
            return self._latest_raw

    def start(self) -> None:
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name="camera")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log.error("Camera thread did not stop within 5 s")

    def _configure(self, camera: pylon.InstantCamera) -> None:
        cam = camera.GetNodeMap()

        for name, value in [
            ("ExposureAuto", "Continuous"),
            ("GainAuto", "Continuous"),
            ("BalanceWhiteAuto", "Once"),
        ]:
            try:
                cam.GetNode(name).SetValue(value)
            except Exception as exc:
                log.warning("%s not available: %s", name, exc)

        try:
            upper = cam.GetNode("AutoExposureTimeUpperLimit")
            limit = min(self._config.auto_exposure_max_us, int(upper.GetMax()))
            upper.SetValue(limit)
            log.info("AutoExposureTimeUpperLimit = %d µs", limit)
        except Exception as exc:
            log.warning("AutoExposureTimeUpperLimit not available: %s", exc)

        for dim in ("Width", "Height"):
            try:
                node = cam.GetNode(dim)
                node.SetValue(node.GetMax())
            except Exception as exc:
                log.warning("%s max not settable: %s", dim, exc)

        try:
            pf_node = cam.GetNode("PixelFormat")
            available = pf_node.GetSymbolics()
            for fmt in _PIXEL_FORMAT_PREFERENCE:
                if fmt in available:
                    pf_node.SetValue(fmt)
                    log.info("PixelFormat = %s", fmt)
                    break
        except Exception as exc:
            log.warning("PixelFormat not configurable: %s", exc)

    def _grab_loop(self) -> None:
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        backoff = 1.0
        while not self._stop_event.is_set():
            camera: pylon.InstantCamera | None = None
            try:
                camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
                camera.Open()
                with self._raw_lock:
                    self._model_name = camera.GetDeviceInfo().GetModelName()
                    self._connected = True
                self._hub.broadcast_status(True)
                log.info("Camera opened: %s", self._model_name)
                backoff = 1.0  # reset on successful connect

                self._configure(camera)
                camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                log.info("Grab loop started")

                while not self._stop_event.is_set() and camera.IsGrabbing():
                    try:
                        grab = camera.RetrieveResult(200, pylon.TimeoutHandling_Return)
                    except pylon.GenericException as exc:
                        log.warning("RetrieveResult error: %s", exc)
                        continue

                    if grab is None:
                        continue

                    try:
                        if grab.GrabSucceeded():
                            rgb = converter.Convert(grab)
                            arr: np.ndarray = rgb.GetArray()
                            jpeg = self._encoder.encode(arr, self._config.stream_quality)
                            with self._raw_lock:
                                self._latest_raw = arr.copy()
                            self._hub.broadcast(jpeg)
                        else:
                            log.warning("Grab failed: %s", grab.ErrorDescription)
                    finally:
                        grab.Release()

            except pylon.GenericException as exc:
                log.warning("Camera error: %s \u2014 retrying in %.0f s", exc, backoff)
            finally:
                with self._raw_lock:
                    self._connected = False
                self._hub.broadcast_status(False)
                if camera is not None:
                    try:
                        camera.StopGrabbing()
                        camera.Close()
                    except Exception:
                        pass
                    log.info("Camera closed")

            if not self._stop_event.is_set():
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
```

**Step 2: Run all tests**

```bash
pytest -v
```

Expected: all tests PASS (hub, config, encoding).

**Step 3: Lint and type-check**

```bash
ruff check src/basler_camera_daemon/camera.py
ruff format --check src/basler_camera_daemon/camera.py
mypy src
```

**Step 4: Commit**

```bash
git add src/basler_camera_daemon/camera.py
git commit -m "feat: camera reconnect loop with exponential backoff and is_connected property"
```

---

### Task 3: `server.py` — handle `bytes | str` + send initial status on connect

**Files:**
- Modify: `src/basler_camera_daemon/server.py`

**Step 1: Replace `_handle_stream` in `src/basler_camera_daemon/server.py`**

The only method that changes is `_handle_stream`. Replace it (lines 60–80 in current file):

```python
    async def _handle_stream(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        q: asyncio.Queue[bytes | str] = asyncio.Queue(maxsize=1)
        self._hub.add(q)
        # Send current camera state immediately so the viewer overlay is correct on connect.
        q.put_nowait(
            '{"type":"status","connected":true}'
            if self._camera.is_connected
            else '{"type":"status","connected":false}'
        )
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
```

**Step 2: Run all tests**

```bash
pytest -v
```

Expected: all PASS.

**Step 3: Lint and type-check**

```bash
ruff check src/basler_camera_daemon/server.py
ruff format --check src/basler_camera_daemon/server.py
mypy src
```

**Step 4: Commit**

```bash
git add src/basler_camera_daemon/server.py
git commit -m "feat: stream handler sends bytes or str; push initial camera status on connect"
```

---

### Task 4: `viewer.html` — camera disconnect overlay

**Files:**
- Modify: `src/basler_camera_daemon/static/viewer.html`

**Step 1: Replace `src/basler_camera_daemon/static/viewer.html` entirely**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Basler Camera</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #111; color: #eee; font-family: system-ui, sans-serif;
           display: flex; flex-direction: column; height: 100vh; }
    header { padding: 12px 20px; background: #1a1a1a; display: flex;
             align-items: center; gap: 16px; }
    h1 { font-size: 1rem; font-weight: 600; }
    #model { color: #888; font-size: 0.875rem; }
    #status { margin-left: auto; font-size: 0.8rem; padding: 4px 10px;
              border-radius: 12px; background: #333; }
    #status.connected    { background: #1a3a1a; color: #4ade80; }
    #status.disconnected { background: #3a1a1a; color: #f87171; }
    main { flex: 1; display: flex; align-items: center; justify-content: center;
           overflow: hidden; padding: 16px; position: relative; }
    #feed { max-width: 100%; max-height: 100%; object-fit: contain;
            border-radius: 4px; background: #222; }
    #cam-overlay { display: none; position: absolute; inset: 16px;
                   background: rgba(0,0,0,0.65); align-items: center;
                   justify-content: center; font-size: 1rem; color: #f87171;
                   border-radius: 4px; pointer-events: none; }
    footer { padding: 12px 20px; background: #1a1a1a; display: flex;
             gap: 12px; align-items: center; }
    button { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer;
             font-size: 0.875rem; font-weight: 500; }
    #btn-capture { background: #2563eb; color: #fff; }
    #btn-capture:hover    { background: #1d4ed8; }
    #btn-capture:disabled { opacity: 0.5; cursor: not-allowed; }
  </style>
</head>
<body>
  <header>
    <h1>Basler Camera</h1>
    <span id="model">&mdash;</span>
    <span id="status">connecting&hellip;</span>
  </header>
  <main>
    <img id="feed" alt="Live stream">
    <div id="cam-overlay">Camera disconnected</div>
  </main>
  <footer>
    <button id="btn-capture" disabled>Capture</button>
  </footer>
  <script>
    const feed       = document.getElementById("feed");
    const statusEl   = document.getElementById("status");
    const modelEl    = document.getElementById("model");
    const btnCapture = document.getElementById("btn-capture");
    const camOverlay = document.getElementById("cam-overlay");

    function refreshModel() {
      fetch("/health").then(r => r.json()).then(d => {
        modelEl.textContent = d.model || "\u2014";
      }).catch(() => {});
    }
    refreshModel();

    let prevUrl = null;
    function connect() {
      const ws = new WebSocket(`ws://${location.host}/stream`);
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        statusEl.textContent = "live";
        statusEl.className = "connected";
        btnCapture.disabled = false;
      };
      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          if (prevUrl) URL.revokeObjectURL(prevUrl);
          const blob = new Blob([e.data], { type: "image/jpeg" });
          prevUrl = URL.createObjectURL(blob);
          feed.src = prevUrl;
        } else {
          const msg = JSON.parse(e.data);
          if (msg.type === "status") {
            camOverlay.style.display = msg.connected ? "none" : "flex";
            if (msg.connected) refreshModel();
          }
        }
      };
      ws.onclose = () => {
        statusEl.textContent = "disconnected \u2014 retrying\u2026";
        statusEl.className = "disconnected";
        btnCapture.disabled = true;
        setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }
    connect();

    btnCapture.addEventListener("click", async () => {
      btnCapture.disabled = true;
      try {
        const r = await fetch("/capture", { method: "POST" });
        const d = await r.json();
        if (d.image_base64) {
          const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, -1);
          const a = document.createElement("a");
          a.href = "data:image/jpeg;base64," + d.image_base64;
          a.download = `capture-${ts}.jpg`;
          a.click();
        }
      } finally {
        btnCapture.disabled = false;
      }
    });
  </script>
</body>
</html>
```

**Step 2: Run all tests**

```bash
pytest -v
```

Expected: all PASS (viewer.html is not unit-tested; this confirms no regressions).

**Step 3: Lint**

```bash
ruff check src && ruff format --check src
mypy src
```

**Step 4: Commit**

```bash
git add src/basler_camera_daemon/static/viewer.html
git commit -m "feat: viewer disconnect overlay driven by WebSocket status messages"
```

---

### Task 5: `__main__.py` — argparse CLI subcommands

**Files:**
- Modify: `src/basler_camera_daemon/__main__.py`

**Step 1: Replace `src/basler_camera_daemon/__main__.py` entirely**

```python
from __future__ import annotations

import argparse
import logging
import os
import sys

from aiohttp import web

from .camera import CameraService
from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub
from .server import WebServer

log = logging.getLogger(__name__)


def _run() -> None:
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


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="basler-daemon", description="Basler camera daemon")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Run in the foreground (default)")
    sub.add_parser("install", help="Register as an OS service with autostart")
    sub.add_parser("uninstall", help="Remove the OS service")
    sub.add_parser("start", help="Start the OS service")
    sub.add_parser("stop", help="Stop the OS service")

    args = parser.parse_args()

    if args.command is None or args.command == "run":
        _run()
        return

    from . import service_manager  # noqa: PLC0415

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
```

Note: `# noqa: PLC0415` suppresses the "import not at top of file" lint warning for the intentional lazy import. ruff's `C` rules are not in our `select` list so this noqa is not strictly necessary — remove it if ruff complains about it.

**Step 2: Run all tests**

```bash
pytest -v
```

Expected: all PASS.

**Step 3: Lint and type-check**

```bash
ruff check src/basler_camera_daemon/__main__.py
ruff format --check src/basler_camera_daemon/__main__.py
mypy src
```

**Step 4: Commit**

```bash
git add src/basler_camera_daemon/__main__.py
git commit -m "feat: argparse CLI with run/install/uninstall/start/stop subcommands"
```

---

### Task 6: `service_manager.py` + `pyproject.toml` updates

**Files:**
- Create: `src/basler_camera_daemon/service_manager.py`
- Modify: `pyproject.toml`

**Step 1: Update `pyproject.toml`**

Add `pywin32` to `[project.dependencies]` and add mypy overrides for win32 modules.

In `[project.dependencies]`, add after `"pypylon>=4.0"`:
```toml
    "pywin32; sys_platform == 'win32'",
```

After the existing `[[tool.mypy.overrides]]` block for pypylon, add:
```toml
[[tool.mypy.overrides]]
module = ["win32service", "win32serviceutil", "win32event", "win32api", "pywintypes"]
ignore_missing_imports = true
```

**Step 2: Create `src/basler_camera_daemon/service_manager.py`**

```python
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
    import os  # noqa: E402
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
            host = os.environ.get("BASLER_HOST", "127.0.0.1")
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
```

**Note on mypy:** The `if sys.platform == "win32":` block is skipped by mypy when running on macOS (mypy treats `sys.platform == "win32"` as always-false on darwin). The `# type: ignore[import-untyped]` comments on win32 imports handle the case if mypy is ever run on Windows.

**Note on Windows Service registration:** This works when `basler-daemon` is installed as a Python package via `pip install`. It registers the service class by its Python module path, so Python must be present on the machine. The PyInstaller exe bundle does not support `install`/`uninstall` (deferred to a future task).

**Step 3: Run all tests**

```bash
pytest -v
```

Expected: all PASS.

**Step 4: Lint and type-check**

```bash
ruff check src tests && ruff format --check src tests
mypy src
```

If ruff flags the `# noqa: E402` comments as unnecessary (because our config doesn't select E402), remove them. If mypy complains about `_win_install` being undefined in `def install()`, add `[[tool.mypy.overrides]] module = "basler_camera_daemon.service_manager" ignore_errors = true` to pyproject.toml as a last resort.

**Step 5: Run full check suite**

```bash
ruff check src tests && ruff format --check src tests && mypy src && pytest -v
```

All should pass.

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/service_manager.py pyproject.toml
git commit -m "feat: OS service registration via launchd (macOS) and pywin32 (Windows)"
```
