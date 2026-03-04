# Basler Camera Daemon — Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure `daemon.py` into a proper installable Python package with SOLID architecture, Ruff, mypy, pytest, and a self-contained Windows build via GitHub Actions.

**Architecture:** Each concern lives in its own class (`CameraConfig`, `ImageEncoder`, `FrameHub`, `CameraService`, `WebServer`). Dependencies are injected via constructors — no global state. The entry point in `__main__.py` wires everything together.

**Tech Stack:** Python 3.13, aiohttp, pypylon, Pillow, Ruff, mypy (strict), pytest + pytest-asyncio, hatchling, PyInstaller.

---

## Task 1: Bootstrap package structure

**Files:**
- Create: `src/basler_camera_daemon/__init__.py`
- Create: `src/basler_camera_daemon/__main__.py`
- Create: `src/basler_camera_daemon/config.py`
- Create: `src/basler_camera_daemon/encoding.py`
- Create: `src/basler_camera_daemon/hub.py`
- Create: `src/basler_camera_daemon/camera.py`
- Create: `src/basler_camera_daemon/server.py`
- Create: `src/basler_camera_daemon/static/.gitkeep`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.github/workflows/build-windows.yml` (empty for now)

**Step 1: Create the directory tree**

```bash
mkdir -p src/basler_camera_daemon/static
mkdir -p tests
mkdir -p .github/workflows
```

**Step 2: Create empty placeholder files**

```bash
touch src/basler_camera_daemon/__init__.py
touch src/basler_camera_daemon/__main__.py
touch src/basler_camera_daemon/config.py
touch src/basler_camera_daemon/encoding.py
touch src/basler_camera_daemon/hub.py
touch src/basler_camera_daemon/camera.py
touch src/basler_camera_daemon/server.py
touch src/basler_camera_daemon/static/.gitkeep
touch tests/__init__.py
touch tests/conftest.py
```

**Step 3: Commit**

```bash
git add src/ tests/ .github/
git commit -m "chore: scaffold package directory structure"
```

---

## Task 2: pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Delete: `requirements.txt` (deps move to pyproject.toml; keep file but strip content to a note)

**Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "basler-camera-daemon"
version = "0.1.0"
description = "HTTP + WebSocket daemon for Basler cameras"
requires-python = ">=3.13"
dependencies = [
    "aiohttp>=3.9",
    "Pillow>=10.0",
    "pypylon>=3.0",
]

[project.optional-dependencies]
dev   = ["ruff", "mypy", "pytest", "pytest-asyncio"]
build = ["pyinstaller"]

[project.scripts]
basler-daemon = "basler_camera_daemon.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/basler_camera_daemon"]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
strict = true
python_version = "3.13"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

**Step 2: Replace `requirements.txt` with a pointer**

```
# Dependencies are managed in pyproject.toml.
# Dev install: pip install -e ".[dev]"
```

**Step 3: Install the package in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: no errors. `basler-daemon` command is now available in your shell.

**Step 4: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "chore: add pyproject.toml with hatchling, ruff, mypy, pytest config"
```

---

## Task 3: CameraConfig (TDD)

**Files:**
- Modify: `src/basler_camera_daemon/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from basler_camera_daemon.config import CameraConfig


def test_defaults(monkeypatch):
    monkeypatch.delenv("BASLER_PORT", raising=False)
    monkeypatch.delenv("BASLER_AUTO_EXPOSURE_MAX_US", raising=False)
    config = CameraConfig.from_env()
    assert config.port == 8082
    assert config.auto_exposure_max_us == 10000
    assert config.stream_quality == 60
    assert config.capture_quality == 92


def test_env_port_override(monkeypatch):
    monkeypatch.setenv("BASLER_PORT", "9000")
    config = CameraConfig.from_env()
    assert config.port == 9000


def test_env_exposure_override(monkeypatch):
    monkeypatch.setenv("BASLER_AUTO_EXPOSURE_MAX_US", "5000")
    config = CameraConfig.from_env()
    assert config.auto_exposure_max_us == 5000


def test_invalid_port_raises(monkeypatch):
    monkeypatch.setenv("BASLER_PORT", "not_a_number")
    with pytest.raises(ValueError):
        CameraConfig.from_env()


def test_config_is_immutable():
    config = CameraConfig.from_env()
    with pytest.raises(Exception):
        config.port = 1234  # type: ignore[misc]
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` or `AttributeError` — `CameraConfig` does not exist yet.

**Step 3: Implement `CameraConfig`**

`src/basler_camera_daemon/config.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraConfig:
    port: int = 8082
    auto_exposure_max_us: int = 10000
    stream_quality: int = 60
    capture_quality: int = 92

    @classmethod
    def from_env(cls) -> CameraConfig:
        return cls(
            port=int(os.environ.get("BASLER_PORT", 8082)),
            auto_exposure_max_us=int(
                os.environ.get("BASLER_AUTO_EXPOSURE_MAX_US", 10000)
            ),
        )
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 5 passed.

**Step 5: Run ruff and mypy**

```bash
ruff check src/basler_camera_daemon/config.py
ruff format src/basler_camera_daemon/config.py
mypy src/basler_camera_daemon/config.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/config.py tests/test_config.py
git commit -m "feat: add CameraConfig dataclass with env-var loading"
```

---

## Task 4: ImageEncoder (TDD)

**Files:**
- Modify: `src/basler_camera_daemon/encoding.py`
- Create: `tests/test_encoding.py`

**Step 1: Write the failing tests**

`tests/test_encoding.py`:
```python
import numpy as np
from basler_camera_daemon.encoding import ImageEncoder


def _solid_frame(h: int = 4, w: int = 4) -> np.ndarray:
    """Return a small solid-colour RGB array."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _is_jpeg(data: bytes) -> bool:
    return data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"


def test_encode_returns_bytes():
    encoder = ImageEncoder()
    result = encoder.encode(_solid_frame(), quality=60)
    assert isinstance(result, bytes)


def test_encode_produces_valid_jpeg():
    encoder = ImageEncoder()
    result = encoder.encode(_solid_frame(), quality=60)
    assert _is_jpeg(result)


def test_higher_quality_produces_larger_file():
    encoder = ImageEncoder()
    # Use a noisy image so compression ratio varies meaningfully with quality
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    low = encoder.encode(noisy, quality=10)
    high = encoder.encode(noisy, quality=95)
    assert len(high) > len(low)


def test_encode_various_resolutions():
    encoder = ImageEncoder()
    for h, w in [(4, 4), (64, 64), (480, 640)]:
        result = encoder.encode(_solid_frame(h, w), quality=60)
        assert _is_jpeg(result), f"Not a JPEG for {h}x{w}"
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_encoding.py -v
```

Expected: `ImportError` — `ImageEncoder` does not exist yet.

**Step 3: Implement `ImageEncoder`**

`src/basler_camera_daemon/encoding.py`:
```python
from __future__ import annotations

import io

import numpy as np
from PIL import Image


class ImageEncoder:
    def encode(self, arr: np.ndarray, quality: int) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_encoding.py -v
```

Expected: 4 passed.

**Step 5: Run ruff and mypy**

```bash
ruff check src/basler_camera_daemon/encoding.py
ruff format src/basler_camera_daemon/encoding.py
mypy src/basler_camera_daemon/encoding.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/encoding.py tests/test_encoding.py
git commit -m "feat: add ImageEncoder (PIL JPEG encoding)"
```

---

## Task 5: FrameHub (TDD)

**Files:**
- Modify: `src/basler_camera_daemon/hub.py`
- Create: `tests/test_hub.py`

**Step 1: Write the failing tests**

`tests/test_hub.py`:
```python
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
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_hub.py -v
```

Expected: `ImportError` — `FrameHub` does not exist yet.

**Step 3: Implement `FrameHub`**

`src/basler_camera_daemon/hub.py`:
```python
from __future__ import annotations

import asyncio
import threading


class FrameHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[asyncio.Queue[bytes]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self, queue: asyncio.Queue[bytes]) -> None:
        with self._lock:
            self._clients.add(queue)

    def remove(self, queue: asyncio.Queue[bytes]) -> None:
        with self._lock:
            self._clients.discard(queue)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, frame: bytes) -> None:
        """Fan-out to all subscribers. Safe to call from any thread."""
        if self._loop is None:
            return
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            def _put(q: asyncio.Queue[bytes] = q) -> None:
                try:
                    q.put_nowait(frame)
                except asyncio.QueueFull:
                    pass
            self._loop.call_soon_threadsafe(_put)
```

**Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_hub.py -v
```

Expected: 7 passed.

**Step 5: Run ruff and mypy**

```bash
ruff check src/basler_camera_daemon/hub.py
ruff format src/basler_camera_daemon/hub.py
mypy src/basler_camera_daemon/hub.py
```

Expected: no errors.

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/hub.py tests/test_hub.py
git commit -m "feat: add FrameHub (thread-safe WebSocket fan-out)"
```

---

## Task 6: conftest.py

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Write shared fixtures**

`tests/conftest.py`:
```python
import numpy as np
import pytest


@pytest.fixture
def rgb_frame() -> np.ndarray:
    """4×4 black RGB frame for testing. No camera hardware required."""
    return np.zeros((4, 4, 3), dtype=np.uint8)
```

**Step 2: Verify all existing tests still pass**

```bash
pytest tests/ -v
```

Expected: all tests pass.

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add shared rgb_frame fixture to conftest"
```

---

## Task 7: Extract viewer.html

**Files:**
- Create: `src/basler_camera_daemon/static/viewer.html`

**Step 1: Copy the HTML out of `daemon.py`**

Take the string assigned to `_VIEWER_HTML` in the original `daemon.py` (lines 239–338) and save it as a standalone HTML file. Remove the Python string delimiters — the file should start with `<!DOCTYPE html>` and end with `</html>`.

`src/basler_camera_daemon/static/viewer.html`:
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
           overflow: hidden; padding: 16px; gap: 16px; }
    #feed { max-width: 100%; max-height: 100%; object-fit: contain;
            border-radius: 4px; background: #222; }
    footer { padding: 12px 20px; background: #1a1a1a; display: flex;
             gap: 12px; align-items: center; }
    button { padding: 8px 20px; border: none; border-radius: 6px; cursor: pointer;
             font-size: 0.875rem; font-weight: 500; }
    #btn-capture { background: #2563eb; color: #fff; }
    #btn-capture:hover    { background: #1d4ed8; }
    #btn-capture:disabled { opacity: 0.5; cursor: not-allowed; }
    #capture-label { font-size: 0.8rem; color: #888; }
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
  </main>
  <footer>
    <button id="btn-capture" disabled>Capture</button>
  </footer>
  <script>
    const feed         = document.getElementById("feed");
    const statusEl     = document.getElementById("status");
    const modelEl      = document.getElementById("model");
    const btnCapture = document.getElementById("btn-capture");

    fetch("/health").then(r => r.json()).then(d => {
      modelEl.textContent = d.model || "\u2014";
    }).catch(() => {});

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
        if (prevUrl) URL.revokeObjectURL(prevUrl);
        const blob = new Blob([e.data], { type: "image/jpeg" });
        prevUrl = URL.createObjectURL(blob);
        feed.src = prevUrl;
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

Note: Replace the Unicode escape sequences (`\u2014`, `\u2026`) with their HTML entity equivalents (`&mdash;`, `&hellip;`) since this is now a real HTML file.

**Step 2: Commit**

```bash
git add src/basler_camera_daemon/static/viewer.html
git commit -m "feat: extract viewer HTML into static/viewer.html"
```

---

## Task 8: CameraService

No unit tests — this class directly owns pylon hardware. It is tested manually with a real camera.

**Files:**
- Modify: `src/basler_camera_daemon/camera.py`

**Step 1: Implement `CameraService`**

`src/basler_camera_daemon/camera.py`:
```python
from __future__ import annotations

import logging
import threading

import numpy as np
from pypylon import pylon

from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

log = logging.getLogger(__name__)

_PIXEL_FORMAT_PREFERENCE = [
    "BayerRG8", "BayerGB8", "BayerGR8", "BayerBG8", "RGB8", "BGR8", "Mono8"
]


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
        self._model_name = "unknown"
        self._raw_lock = threading.Lock()
        self._latest_raw: np.ndarray | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def get_latest_raw(self) -> np.ndarray | None:
        with self._raw_lock:
            return self._latest_raw

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._grab_loop, daemon=True, name="camera"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _configure(self, camera: pylon.InstantCamera) -> None:
        cam = camera.GetNodeMap()

        for name, value in [
            ("ExposureAuto", "Continuous"),
            ("GainAuto", "Continuous"),
            ("BalanceWhiteAuto", "Once"),
        ]:
            try:
                cam.GetNode(name).SetValue(value)
            except Exception:
                log.warning("%s not available", name)

        try:
            upper = cam.GetNode("AutoExposureTimeUpperLimit")
            limit = min(self._config.auto_exposure_max_us, int(upper.GetMax()))
            upper.SetValue(limit)
            log.info("AutoExposureTimeUpperLimit = %d µs", limit)
        except Exception:
            log.warning("AutoExposureTimeUpperLimit not available")

        for dim in ("Width", "Height"):
            try:
                node = cam.GetNode(dim)
                node.SetValue(node.GetMax())
            except Exception:
                log.warning("%s max not settable", dim)

        try:
            pf_node = cam.GetNode("PixelFormat")
            available = pf_node.GetSymbolics()
            for fmt in _PIXEL_FORMAT_PREFERENCE:
                if fmt in available:
                    pf_node.SetValue(fmt)
                    log.info("PixelFormat = %s", fmt)
                    break
        except Exception:
            log.warning("PixelFormat not configurable")

    def _grab_loop(self) -> None:
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        camera: pylon.InstantCamera | None = None
        try:
            camera = pylon.InstantCamera(
                pylon.TlFactory.GetInstance().CreateFirstDevice()
            )
            camera.Open()
            self._model_name = camera.GetDeviceInfo().GetModelName()
            log.info("Camera opened: %s", self._model_name)

            self._configure(camera)
            camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            log.info("Grab loop started")

            while not self._stop_event.is_set():
                if not camera.IsGrabbing():
                    log.warning("Camera stopped grabbing unexpectedly")
                    break

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
                            self._latest_raw = arr
                        self._hub.broadcast(jpeg)
                    else:
                        log.warning("Grab failed: %s", grab.ErrorDescription)
                finally:
                    grab.Release()

        except pylon.GenericException as exc:
            log.error("Camera error: %s", exc)
        finally:
            if camera is not None:
                try:
                    camera.StopGrabbing()
                    camera.Close()
                except Exception:
                    pass
                log.info("Camera closed")
```

**Step 2: Run ruff and mypy**

```bash
ruff check src/basler_camera_daemon/camera.py
ruff format src/basler_camera_daemon/camera.py
mypy src/basler_camera_daemon/camera.py
```

Expected: no errors. (mypy may warn about pypylon stubs — acceptable to add `# type: ignore[import-untyped]` on the pypylon import if needed.)

**Step 3: Commit**

```bash
git add src/basler_camera_daemon/camera.py
git commit -m "feat: add CameraService (pylon grab loop with DI)"
```

---

## Task 9: WebServer

No unit tests — testing an aiohttp server requires a running event loop and integration harness. Tested manually.

**Files:**
- Modify: `src/basler_camera_daemon/server.py`

**Step 1: Implement `WebServer`**

`src/basler_camera_daemon/server.py`:
```python
from __future__ import annotations

import asyncio
import base64
import importlib.resources
import logging

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

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
        self._hub.set_loop(asyncio.get_event_loop())
        self._camera.start()

    async def _on_shutdown(self, app: web.Application) -> None:
        log.info("Server shutting down, stopping camera…")
        self._camera.stop()

    async def _handle_viewer(self, request: web.Request) -> web.Response:
        return web.Response(text=self._viewer_html, content_type="text/html")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "model": self._camera.model_name})

    async def _handle_stream(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1)
        self._hub.add(q)
        log.info("WS client connected (%d total)", self._hub.client_count())
        try:
            while not ws.closed:
                try:
                    frame = await asyncio.wait_for(q.get(), timeout=5.0)
                    await ws.send_bytes(frame)
                except asyncio.TimeoutError:
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
```

**Step 2: Run ruff and mypy**

```bash
ruff check src/basler_camera_daemon/server.py
ruff format src/basler_camera_daemon/server.py
mypy src/basler_camera_daemon/server.py
```

Expected: no errors.

**Step 3: Commit**

```bash
git add src/basler_camera_daemon/server.py
git commit -m "feat: add WebServer (aiohttp app with injected dependencies)"
```

---

## Task 10: `__init__.py` and `__main__.py`

**Files:**
- Modify: `src/basler_camera_daemon/__init__.py`
- Modify: `src/basler_camera_daemon/__main__.py`

**Step 1: Write `__init__.py`**

`src/basler_camera_daemon/__init__.py`:
```python
__version__ = "0.1.0"
```

**Step 2: Write `__main__.py`**

`src/basler_camera_daemon/__main__.py`:
```python
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
```

**Step 3: Run ruff and mypy on both files**

```bash
ruff check src/basler_camera_daemon/__init__.py src/basler_camera_daemon/__main__.py
ruff format src/basler_camera_daemon/__init__.py src/basler_camera_daemon/__main__.py
mypy src/basler_camera_daemon/__init__.py src/basler_camera_daemon/__main__.py
```

Expected: no errors.

**Step 4: Commit**

```bash
git add src/basler_camera_daemon/__init__.py src/basler_camera_daemon/__main__.py
git commit -m "feat: add package entry points (__init__, __main__)"
```

---

## Task 11: GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/build-windows.yml`

**Step 1: Write the workflow**

`.github/workflows/build-windows.yml`:
```yaml
name: Build Windows Executable

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: pip install -e ".[build]"

      - name: Build executable
        run: >
          pyinstaller
          --onefile
          --name basler-daemon
          --collect-all pypylon
          --collect-data basler_camera_daemon
          src/basler_camera_daemon/__main__.py

      - name: Upload artefact
        uses: actions/upload-artifact@v4
        with:
          name: basler-daemon-windows
          path: dist/basler-daemon.exe
          if-no-files-found: error
```

Note: `--collect-data basler_camera_daemon` ensures `static/viewer.html` is bundled alongside the pypylon DLLs. `--collect-all pypylon` handles the pylon runtime DLLs from the pypylon wheel.

**Step 2: Commit**

```bash
git add .github/workflows/build-windows.yml
git commit -m "ci: add Windows executable build workflow"
```

---

## Task 12: Full verification

**Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (config, encoding, hub).

**Step 2: Run ruff over the entire package**

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

Expected: no issues.

**Step 3: Run mypy over the entire package**

```bash
mypy src/basler_camera_daemon/
```

Expected: no errors. If pypylon lacks type stubs, add to `pyproject.toml`:
```toml
[[tool.mypy.overrides]]
module = "pypylon.*"
ignore_missing_imports = true
```

**Step 4: Verify the package is importable**

```bash
python -c "from basler_camera_daemon.config import CameraConfig; print(CameraConfig.from_env())"
```

Expected: prints the default config.

**Step 5: Verify the entry point exists**

```bash
basler-daemon --help 2>&1 || true
```

Expected: aiohttp startup output or usage info — confirms the entry point resolves.

**Step 6: Commit any fixes**

```bash
git add -p
git commit -m "fix: address ruff/mypy issues found in full verification"
```

---

## Task 13: Remove the old god script

**Files:**
- Delete: `daemon.py`
- Modify: `README.md`

**Step 1: Delete `daemon.py`**

```bash
git rm daemon.py
```

**Step 2: Update `README.md` install and run sections**

Replace the `Installation` and `Running` sections with:

```markdown
## Installation

Requires Python 3.13+ and the Basler pylon SDK (macOS/Linux only — Windows users run the pre-built exe).

```bash
pip install -e ".[dev]"
```

## Running

```bash
basler-daemon
# or
python -m basler_camera_daemon
```
```

**Step 3: Commit**

```bash
git add daemon.py README.md
git commit -m "chore: remove daemon.py god script, update README for package install"
```

---

## Final state

```
basler-camera-daemon/
├── src/basler_camera_daemon/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   ├── encoding.py
│   ├── hub.py
│   ├── camera.py
│   ├── server.py
│   └── static/viewer.html
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_encoding.py
│   └── test_hub.py
├── .github/workflows/build-windows.yml
├── docs/plans/
├── pyproject.toml
├── requirements.txt
└── README.md
```

`pytest tests/ -v` → all green.
`ruff check src/ tests/` → clean.
`mypy src/basler_camera_daemon/` → clean.
`basler-daemon` → server starts on port 8082.
Push to `main` → GitHub Actions builds `basler-daemon.exe` on `windows-latest`.
