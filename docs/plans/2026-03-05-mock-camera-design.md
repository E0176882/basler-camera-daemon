# Basler Camera Daemon — Mock Camera Mode Design

**Date:** 2026-03-05
**Status:** Approved

## Context

Development and testing without a physical Basler camera requires a synthetic feed. This design adds a `--mock` flag to `basler-daemon run` that substitutes a `MockCameraService` generating an animated SMPTE color-bar test card at 30 fps.

## Files Changed

| File | Change |
|---|---|
| `src/basler_camera_daemon/mock_camera.py` | NEW — `MockCameraService` with color-bar + timestamp frame generation |
| `src/basler_camera_daemon/__main__.py` | Add `--mock` flag to `run` subcommand; factory selects `MockCameraService` vs `CameraService` |
| `pyproject.toml` | Add `Pillow>=10` to `[project.dependencies]` |
| `tests/test_mock_camera.py` | NEW — 3 tests: frame generation, `is_connected`, `broadcast_status` |

## Section 1: Architecture

`MockCameraService` is a drop-in replacement for `CameraService` with an identical API:

| Method/property | Behavior |
|---|---|
| `start()` | Starts background thread, calls `hub.broadcast_status(True)` |
| `stop()` | Sets stop event, joins thread, calls `hub.broadcast_status(False)` |
| `is_connected: bool` | `True` while thread is running |

`__main__.py` factory:

```python
service = MockCameraService(config, hub) if args.mock else CameraService(config, hub)
```

`--mock` is a flag on the `run` subcommand only:

```
basler-daemon run --mock
```

`Pillow>=10` added to `[project.dependencies]` for PIL timestamp text rendering.

No changes to `hub.py`, `server.py`, `viewer.html`, or `encoding.py`.

## Section 2: Frame Generation

The mock thread generates 1280×720 frames at 30 fps:

1. **Color bars** — 8 vertical SMPTE bands (white, yellow, cyan, green, magenta, red, blue, black) built once as a numpy array at `__init__` time and reused each frame
2. **Timestamp** — current time (`HH:MM:SS.mmm`) stamped top-left each frame using `PIL.ImageDraw` with the default bitmap font (no external font files)
3. **Encoding** — PIL image converted to numpy array and passed through existing `ImageEncoder.encode()` (same JPEG encode path as real camera frames)
4. **Timing** — `time.sleep(1/30)` after each frame (no drift compensation needed for a dev tool)

SMPTE color values (RGB):

| Band | Color | RGB |
|---|---|---|
| 1 | White | `(235, 235, 235)` |
| 2 | Yellow | `(235, 235, 16)` |
| 3 | Cyan | `(16, 235, 235)` |
| 4 | Green | `(16, 235, 16)` |
| 5 | Magenta | `(235, 16, 235)` |
| 6 | Red | `(235, 16, 16)` |
| 7 | Blue | `(16, 16, 235)` |
| 8 | Black | `(16, 16, 16)` |

## Section 3: Testing

New `tests/test_mock_camera.py`:

1. **`test_mock_generates_frames`** — starts `MockCameraService` with a `Mock()` stub hub, waits ~150 ms, asserts ≥3 non-empty `bytes` objects broadcast via `hub.broadcast`
2. **`test_mock_is_connected`** — asserts `is_connected` is `False` before `start()`, `True` after, `False` after `stop()`
3. **`test_mock_broadcasts_status`** — asserts `hub.broadcast_status(True)` called on `start()`, `hub.broadcast_status(False)` called on `stop()`

Stub hub uses `unittest.mock.Mock()` — no real asyncio needed since `MockCameraService` calls hub methods synchronously from its thread.

## Testing Strategy

Manual verification:

- `basler-daemon run --mock` → open `http://127.0.0.1:8082` → verify color bars with live timestamp visible
- WebSocket client receives binary JPEG frames at ~30 fps
- `Ctrl-C` → clean shutdown, no errors
