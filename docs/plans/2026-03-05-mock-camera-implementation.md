# Mock Camera Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `basler-daemon run --mock` that streams a synthetic SMPTE color-bar test card at 30 fps so the full daemon runs without physical hardware.

**Architecture:** `MockCameraService` in `mock_camera.py` implements a new `CameraProtocol` (structural Protocol) alongside the existing `CameraService`. `WebServer` is updated to accept `CameraProtocol` instead of the concrete class, removing the coupling. `__main__.py` adds a `--mock` flag to the `run` subcommand and selects the appropriate service at startup.

**Tech Stack:** Python 3.13, numpy, Pillow (already dependencies), `typing.Protocol` for structural subtyping, pytest + `unittest.mock.Mock`.

---

### Task 1: Extract `CameraProtocol`

This decouples `WebServer` from the concrete `CameraService` so it can accept `MockCameraService` too. No functional change — just type plumbing.

**Files:**
- Create: `src/basler_camera_daemon/camera_protocol.py`
- Modify: `src/basler_camera_daemon/server.py` (lines 10, 22)

**Step 1: Write the failing mypy check**

There is no pytest test for this task — it is verified by mypy passing after the change. Skip ahead to Step 2.

**Step 2: Create `src/basler_camera_daemon/camera_protocol.py`**

```python
from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class CameraProtocol(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def is_connected(self) -> bool: ...

    def get_latest_raw(self) -> np.ndarray[Any, np.dtype[Any]] | None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
```

**Step 3: Update `server.py`**

Replace line 10:
```python
# Before
from .camera import CameraService
# After
from .camera_protocol import CameraProtocol
```

Replace line 22:
```python
# Before
        camera: CameraService,
# After
        camera: CameraProtocol,
```

Replace line 28 (the stored field type — mypy infers this from the parameter, no explicit annotation needed; leave as-is):
```python
        self._camera = camera
```

**Step 4: Verify mypy and tests still pass**

```bash
mypy src/
pytest -q
```

Expected: zero mypy errors, all existing tests pass.

**Step 5: Commit**

```bash
git add src/basler_camera_daemon/camera_protocol.py src/basler_camera_daemon/server.py
git commit -m "refactor: extract CameraProtocol to decouple WebServer from CameraService"
```

---

### Task 2: `MockCameraService`

**Files:**
- Create: `src/basler_camera_daemon/mock_camera.py`
- Create: `tests/test_mock_camera.py`

**Step 1: Write the failing tests**

Create `tests/test_mock_camera.py`:

```python
from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from basler_camera_daemon.config import CameraConfig
from basler_camera_daemon.encoding import ImageEncoder
from basler_camera_daemon.mock_camera import MockCameraService


@pytest.fixture
def config() -> CameraConfig:
    return CameraConfig(port=8082, auto_exposure_max_us=10000, stream_quality=75, capture_quality=92)


@pytest.fixture
def encoder() -> ImageEncoder:
    return ImageEncoder()


def test_mock_is_connected_lifecycle(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    assert service.is_connected is False
    service.start()
    time.sleep(0.05)
    assert service.is_connected is True
    service.stop()
    assert service.is_connected is False


def test_mock_broadcasts_status(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    service.start()
    time.sleep(0.05)
    service.stop()
    assert call(True) in hub.broadcast_status.call_args_list
    assert call(False) in hub.broadcast_status.call_args_list


def test_mock_generates_frames(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    service.start()
    time.sleep(0.15)  # ~4 frames at 30 fps
    service.stop()
    assert hub.broadcast.call_count >= 3
    for c in hub.broadcast.call_args_list:
        frame: bytes = c.args[0]
        assert len(frame) > 0


def test_mock_model_name(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    assert service.model_name == "mock"


def test_mock_get_latest_raw_none_before_start(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    assert service.get_latest_raw() is None


def test_mock_get_latest_raw_after_frames(config: CameraConfig, encoder: ImageEncoder) -> None:
    hub = MagicMock()
    service = MockCameraService(config, encoder, hub)
    service.start()
    time.sleep(0.1)
    service.stop()
    raw = service.get_latest_raw()
    assert raw is not None
    assert raw.shape == (720, 1280, 3)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mock_camera.py -v
```

Expected: `ModuleNotFoundError: No module named 'basler_camera_daemon.mock_camera'`

**Step 3: Implement `src/basler_camera_daemon/mock_camera.py`**

```python
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

# Classic SMPTE 75% color bars (8 bands, RGB values)
_SMPTE_COLORS: list[tuple[int, int, int]] = [
    (235, 235, 235),  # White
    (235, 235, 16),   # Yellow
    (16, 235, 235),   # Cyan
    (16, 235, 16),    # Green
    (235, 16, 235),   # Magenta
    (235, 16, 16),    # Red
    (16, 16, 235),    # Blue
    (16, 16, 16),     # Black
]

_WIDTH = 1280
_HEIGHT = 720
_FPS = 30


class MockCameraService:
    """Synthetic camera that streams a color-bar test card at 30 fps.

    Drop-in replacement for CameraService — implements CameraProtocol.
    No pypylon or physical camera required.
    """

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
        self._lock = threading.Lock()
        self._connected = False
        self._latest_raw: np.ndarray[Any, np.dtype[Any]] | None = None
        self._base = self._make_base()

    @property
    def model_name(self) -> str:
        return "mock"

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def get_latest_raw(self) -> np.ndarray[Any, np.dtype[Any]] | None:
        with self._lock:
            return self._latest_raw

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._generate_loop, daemon=True, name="mock-camera"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _make_base(self) -> np.ndarray[Any, np.dtype[Any]]:
        arr: np.ndarray[Any, np.dtype[Any]] = np.zeros((_HEIGHT, _WIDTH, 3), dtype=np.uint8)
        n = len(_SMPTE_COLORS)
        band = _WIDTH // n
        for i, color in enumerate(_SMPTE_COLORS):
            x_start = i * band
            x_end = x_start + band if i < n - 1 else _WIDTH
            arr[:, x_start:x_end] = color
        return arr

    def _generate_loop(self) -> None:
        with self._lock:
            self._connected = True
        self._hub.broadcast_status(True)
        try:
            while not self._stop_event.is_set():
                frame = self._base.copy()
                img = Image.fromarray(frame)
                draw = ImageDraw.Draw(img)
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                draw.text((10, 10), ts, fill=(255, 255, 255))
                arr: np.ndarray[Any, np.dtype[Any]] = np.array(img)
                jpeg = self._encoder.encode(arr, self._config.stream_quality)
                with self._lock:
                    self._latest_raw = arr
                self._hub.broadcast(jpeg)
                self._stop_event.wait(1.0 / _FPS)
        finally:
            with self._lock:
                self._connected = False
            self._hub.broadcast_status(False)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mock_camera.py -v
```

Expected: 6 tests PASSED.

**Step 5: Verify mypy**

```bash
mypy src/
```

Expected: no errors.

**Step 6: Commit**

```bash
git add src/basler_camera_daemon/mock_camera.py tests/test_mock_camera.py
git commit -m "feat: add MockCameraService with SMPTE color-bar test card"
```

---

### Task 3: Wire `--mock` flag in `__main__.py`

**Files:**
- Modify: `src/basler_camera_daemon/__main__.py`

**Step 1: Update imports at the top of `__main__.py`**

Add after the existing `from .camera import CameraService` import:
```python
from .camera_protocol import CameraProtocol
from .mock_camera import MockCameraService
```

**Step 2: Update `_run()` to accept `mock` parameter**

Replace the current `_run()` function:

```python
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
```

**Step 3: Add `--mock` flag to the `run` subparser**

Replace:
```python
    sub.add_parser("run", help="Run in the foreground (default)")
```
With:
```python
    run_parser = sub.add_parser("run", help="Run in the foreground (default)")
    run_parser.add_argument(
        "--mock",
        action="store_true",
        help="Use synthetic SMPTE test-card feed (no camera required)",
    )
```

**Step 4: Pass `mock` when dispatching `run`**

Replace:
```python
    if args.command is None or args.command == "run":
        _run()
        return
```
With:
```python
    if args.command is None or args.command == "run":
        _run(mock=getattr(args, "mock", False))
        return
```

(`getattr` with default handles the case where no subcommand was given and `args.mock` does not exist.)

**Step 5: Run full test suite and mypy**

```bash
pytest -q
mypy src/
```

Expected: all tests pass, zero mypy errors.

**Step 6: Quick manual smoke test**

```bash
basler-daemon run --mock
# Open http://127.0.0.1:8082 — should see 8 color bars with live timestamp
# Ctrl-C — clean shutdown
```

Expected: color bars visible in browser at ~30 fps, timestamp updates each frame.

**Step 7: Commit**

```bash
git add src/basler_camera_daemon/__main__.py
git commit -m "feat: add --mock flag to 'basler-daemon run' for hardware-free testing"
```

---

### Task 4: Ruff lint pass

**Files:**
- `src/basler_camera_daemon/camera_protocol.py`
- `src/basler_camera_daemon/mock_camera.py`
- `src/basler_camera_daemon/__main__.py`
- `src/basler_camera_daemon/server.py`

**Step 1: Run ruff**

```bash
ruff check src/ --fix
ruff format src/
```

Expected: no unfixed violations.

**Step 2: Re-run full suite**

```bash
pytest -q
mypy src/
```

Expected: all pass.

**Step 3: Commit if any changes**

```bash
git add -u
git commit -m "style: ruff fixes for mock camera changes"
```

(Skip commit if `git diff` is empty.)
