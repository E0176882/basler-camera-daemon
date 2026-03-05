# OpenAPI Documentation & Port Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a static OpenAPI 3.1.0 spec at `docs/openapi.yaml` and harden the daemon to a fixed port (47420) with no host/port env vars.

**Architecture:** Two independent tasks — (1) update code and tests to remove `BASLER_HOST`/`BASLER_PORT` and change port to 47420, (2) write the static OpenAPI YAML file. No new dependencies.

**Tech Stack:** Python 3.13, OpenAPI 3.1.0 YAML, pytest monkeypatch.

---

### Task 1: Port hardening — remove env vars, change port to 47420

**Files:**
- Modify: `src/basler_camera_daemon/config.py`
- Modify: `src/basler_camera_daemon/__main__.py`
- Modify: `tests/test_config.py`
- Modify: `README.md`

**Step 1: Update `tests/test_config.py` to reflect the new contract**

Replace the entire file:

```python
import dataclasses

import pytest

from basler_camera_daemon.config import CameraConfig


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BASLER_AUTO_EXPOSURE_MAX_US", raising=False)
    config = CameraConfig.from_env()
    assert config.port == 47420
    assert config.auto_exposure_max_us == 10000
    assert config.stream_quality == 60
    assert config.capture_quality == 92


def test_env_exposure_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASLER_AUTO_EXPOSURE_MAX_US", "5000")
    config = CameraConfig.from_env()
    assert config.auto_exposure_max_us == 5000


def test_invalid_exposure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASLER_AUTO_EXPOSURE_MAX_US", "not_a_number")
    with pytest.raises(ValueError):
        CameraConfig.from_env()


def test_config_is_immutable() -> None:
    config = CameraConfig.from_env()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.port = 1234  # type: ignore[misc]
```

Removed tests: `test_env_port_override` and `test_invalid_port_raises` — `BASLER_PORT` is no longer supported.

**Step 2: Run tests to verify the right ones fail**

```bash
pytest tests/test_config.py -v
```

Expected: `test_defaults` FAILS (`assert 8082 == 47420`). All other new tests PASS (they test unchanged behaviour).

**Step 3: Update `src/basler_camera_daemon/config.py`**

Replace the entire file:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraConfig:
    port: int = 47420
    auto_exposure_max_us: int = 10000
    stream_quality: int = 60
    capture_quality: int = 92

    @classmethod
    def from_env(cls) -> CameraConfig:
        # stream_quality and capture_quality are internal constants, not env-configurable.
        # port is fixed — the daemon always binds to 127.0.0.1:47420.
        return cls(
            auto_exposure_max_us=int(os.environ.get("BASLER_AUTO_EXPOSURE_MAX_US", 10000)),
        )
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 tests PASS.

**Step 5: Update `src/basler_camera_daemon/__main__.py`**

In `_run()`, replace:

```python
    host = os.environ.get("BASLER_HOST", "127.0.0.1")
```

With:

```python
    host = "127.0.0.1"
```

Also remove the `import os` line if `os` is no longer used anywhere else in the file. Check first — `os` is used in `_run()` only for the host env var, so after this change it is unused and must be removed.

**Step 6: Run the full test suite**

```bash
pytest -q
mypy src/
```

Expected: all tests pass, zero mypy errors.

**Step 7: Update `README.md`**

Make these changes:

1. Replace the env var table (lines 40–44) with:

```markdown
Optional environment variable:

| Variable | Default | Description |
|----------|---------|-------------|
| `BASLER_AUTO_EXPOSURE_MAX_US` | `10000` | Auto-exposure upper limit (µs) |
```

2. Replace every occurrence of `8082` with `47420` (affects the browser viewer URL, curl examples, wscat example, and JS snippet — 6 occurrences total).

**Step 8: Run full suite + ruff**

```bash
pytest -q
mypy src/
ruff check src/ tests/
```

Expected: all pass.

**Step 9: Commit**

```bash
git add src/basler_camera_daemon/config.py src/basler_camera_daemon/__main__.py tests/test_config.py README.md
git commit -m "fix: harden port to 47420, remove BASLER_HOST/BASLER_PORT env vars"
```

---

### Task 2: Create `docs/openapi.yaml`

**Files:**
- Create: `docs/openapi.yaml`

No tests — this is a static document. Verification is done by linting the YAML with `python3 -c "import yaml; yaml.safe_load(open('docs/openapi.yaml'))"`.

**Step 1: Create `docs/openapi.yaml`**

```yaml
openapi: 3.1.0

info:
  title: Basler Camera Daemon
  version: 0.1.0
  description: >
    Localhost HTTP + WebSocket daemon that owns a Basler camera for its lifetime
    and streams live JPEG frames. Always bound to 127.0.0.1:47420.

servers:
  - url: http://127.0.0.1:47420
    description: Local daemon

paths:
  /health:
    get:
      summary: Camera status
      description: Returns camera connection status and model name.
      operationId: getHealth
      responses:
        '200':
          description: Camera is running
          content:
            application/json:
              schema:
                type: object
                required: [status, model]
                properties:
                  status:
                    type: string
                    enum: [ok]
                    example: ok
                  model:
                    type: string
                    description: Camera model name as reported by pypylon
                    example: acA2040-90uc

  /stream:
    get:
      summary: Live camera stream (WebSocket)
      description: |
        Upgrades to a WebSocket connection. The server sends two types of messages:

        **Binary frames** — Raw JPEG bytes at the camera's native frame rate.
        Slow clients silently drop frames (internal queue depth = 1).

        **Text messages** — JSON status notifications sent immediately on connect
        and whenever the camera connects or disconnects:
        ```json
        {"type": "status", "connected": true}
        {"type": "status", "connected": false}
        ```
      operationId: getStream
      responses:
        '101':
          description: Switching Protocols — WebSocket connection established

  /capture:
    post:
      summary: Capture a single frame
      description: >
        Returns the most recently grabbed frame as a high-quality JPEG (quality 92)
        encoded as base64. No data is written to disk.
        Returns 503 if no frame has been grabbed yet (camera not ready).
      operationId: postCapture
      responses:
        '200':
          description: JPEG frame as base64
          content:
            application/json:
              schema:
                type: object
                required: [image_base64]
                properties:
                  image_base64:
                    type: string
                    format: byte
                    description: Base64-encoded JPEG image
        '503':
          description: No frame available yet
          content:
            application/json:
              schema:
                type: object
                required: [error]
                properties:
                  error:
                    type: string
                    example: no frame available
```

**Step 2: Validate the YAML is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('docs/openapi.yaml')); print('valid')"
```

Expected: `valid`

**Step 3: Commit**

```bash
git add docs/openapi.yaml
git commit -m "docs: add OpenAPI 3.1.0 spec for /health, /stream, /capture"
```
