# Basler Camera Daemon — Refactor Design

**Date:** 2026-03-04
**Status:** Approved

## Context

The initial implementation is a single `daemon.py` god script (~425 lines). It mixes camera hardware, frame encoding, WebSocket fan-out, HTTP routing, configuration, and inline HTML in one file with global mutable state throughout. This design makes the code hard to test, maintain, and extend.

The goal is to restructure it into a proper, installable Python package that adheres to SOLID principles, with linting, type checking, tests, and a fully self-contained Windows build via GitHub Actions.

## Constraints

- Python 3.13+
- Cross-platform: macOS (development) and Windows (production)
- Always a single Basler camera
- Linting/formatting: Ruff
- Type checking: mypy (strict)
- Tests: pytest + pytest-asyncio
- End-users on Windows must not need to install Python or the Basler pylon SDK separately

## Package Structure

```
basler-camera-daemon/
├── src/
│   └── basler_camera_daemon/
│       ├── __init__.py          # version only
│       ├── __main__.py          # entry point: python -m basler_camera_daemon
│       ├── config.py            # CameraConfig dataclass (reads env vars)
│       ├── encoding.py          # ImageEncoder (PIL → JPEG bytes)
│       ├── hub.py               # FrameHub (thread-safe WebSocket fan-out)
│       ├── camera.py            # CameraService (grab loop, owns pylon)
│       ├── server.py            # WebServer (aiohttp app + route wiring)
│       └── static/
│           └── viewer.html      # browser viewer (moved from inline string)
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_encoding.py
│   └── test_hub.py
├── docs/
│   └── plans/
├── .github/
│   └── workflows/
│       └── build-windows.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Component Design

### `CameraConfig` (dataclass, `config.py`)

Reads environment variables at construction time. Immutable after init. Passed into `CameraService`.

| Field | Env var | Default |
|---|---|---|
| `port` | `BASLER_PORT` | `8082` |
| `auto_exposure_max_us` | `BASLER_AUTO_EXPOSURE_MAX_US` | `10000` |
| `stream_quality` | — | `60` |
| `capture_quality` | — | `92` |

### `ImageEncoder` (`encoding.py`)

Stateless. Single method: `encode(arr: np.ndarray, quality: int) -> bytes`. Injected into `CameraService`.

### `FrameHub` (`hub.py`)

Owns the set of subscriber asyncio queues. Thread-safe add/remove/broadcast. Holds a reference to the running event loop (set once at server startup via `set_loop()`). Injected into both `CameraService` (to broadcast) and `WebServer` (to subscribe clients).

### `CameraService` (`camera.py`)

Owns the pylon camera lifecycle. Runs in a background thread via `start()` / `stop()`. On each successful grab: calls `ImageEncoder.encode()`, stores the raw array, calls `FrameHub.broadcast()`. Exposes `model_name: str` and `get_latest_raw() -> np.ndarray | None`. Injected with `CameraConfig`, `ImageEncoder`, `FrameHub`.

### `WebServer` (`server.py`)

Builds the aiohttp `Application`. HTTP handlers are methods on `WebServer`, closing over injected `CameraService` and `FrameHub` — no global state. Startup hook sets the event loop on `FrameHub` and starts `CameraService`. Shutdown hook stops `CameraService`.

Serves `viewer.html` via `importlib.resources` so it works from both an editable install and a PyInstaller bundle.

## Data Flow

```
pylon hardware
  → CameraService._grab_loop()
      → ImageEncoder.encode(arr, stream_quality)   # raw → JPEG bytes
      → FrameHub.broadcast(jpeg)                   # fan-out to WS clients
      → self._latest_raw = arr                     # stored for /capture

WebSocket client connects  →  GET /stream
  → WebServer.handle_stream()
      → FrameHub.add(queue)
      → await queue.get() → ws.send_bytes()

POST /capture
  → WebServer.handle_capture()
      → CameraService.get_latest_raw()
      → ImageEncoder.encode(arr, capture_quality)
      → base64 encode → JSON response
```

## Tooling (`pyproject.toml`)

- **Build backend:** `hatchling` (handles `src/` layout, no config needed)
- **Entry point:** `basler-daemon = "basler_camera_daemon.__main__:main"`
- **`[tool.ruff]`** — lint + format, target Python 3.13
- **`[tool.mypy]`** — strict mode
- **`[tool.pytest.ini_options]`** — `testpaths = ["tests"]`

**Dependency groups:**

```toml
[project.optional-dependencies]
dev   = ["ruff", "mypy", "pytest", "pytest-asyncio"]
build = ["pyinstaller"]
```

## Testing Strategy

Tests cover the three hardware-free components. `CameraService` and `WebServer` are not unit tested (hardware/server dependency).

| File | Covers |
|---|---|
| `test_config.py` | Env var parsing, defaults, invalid values |
| `test_encoding.py` | `ImageEncoder.encode()` returns valid JPEG at requested quality |
| `test_hub.py` | `FrameHub` add/remove/broadcast with mocked event loop |

`conftest.py` provides shared fixtures: synthetic numpy frame array, mock asyncio event loop.

`pypylon` is not imported by any test — tests run in CI without the Basler SDK.

## GitHub Actions — Windows Build

**File:** `.github/workflows/build-windows.yml`
**Triggers:** push to `main`, manual `workflow_dispatch`
**Runner:** `windows-latest`

```yaml
steps:
  - Checkout
  - Set up Python 3.13
  - pip install -e ".[build]"       # pypylon wheel bundles pylon runtime DLLs
  - pyinstaller
      --onefile
      --name basler-daemon
      --collect-all pypylon
      src/basler_camera_daemon/__main__.py
  - Upload dist/basler-daemon.exe as build artefact
```

The `pypylon` PyPI wheel ships the pylon runtime DLLs internally. `--collect-all pypylon` causes PyInstaller to bundle them into the exe. End users on Windows require no Python installation and no Basler SDK installation.
