# Basler Camera Daemon — Robustness & OS Service Design

**Date:** 2026-03-04
**Status:** Approved

## Context

The initial refactor produces a working daemon but it dies permanently if the camera disconnects. There is also no mechanism for auto-start on boot or graceful OS service lifecycle. This design adds:

1. Camera reconnection — retry loop with exponential backoff; service stays alive indefinitely
2. Viewer disconnect status — WebSocket status messages; browser shows overlay when camera is down
3. OS service registration — launchd (macOS) and Windows Service (pywin32)
4. CLI subcommands — `install / uninstall / start / stop / run`

## Files Changed

| File | Change |
|---|---|
| `src/basler_camera_daemon/camera.py` | Outer retry loop, `is_connected` property, `broadcast_status` calls |
| `src/basler_camera_daemon/hub.py` | `broadcast_status(bool)` method; queue type `bytes \| str` |
| `src/basler_camera_daemon/server.py` | Stream handler handles `bytes \| str` queue items |
| `src/basler_camera_daemon/static/viewer.html` | Disconnect overlay + status message handling |
| `src/basler_camera_daemon/__main__.py` | `argparse` CLI dispatcher |
| `src/basler_camera_daemon/service_manager.py` | NEW — platform-dispatched service registration |
| `pyproject.toml` | Add `pywin32; sys_platform == 'win32'` dependency |

## Section 1: Camera Reconnection (`camera.py`)

`_grab_loop` wraps connect/grab logic in an outer retry loop. The thread runs until `stop()` is called.

```
while not self._stop_event.is_set():
    try:
        camera = CreateFirstDevice() → Open() → configure() → StartGrabbing()
        self._connected = True
        hub.broadcast_status(True)
        backoff = 1.0  # reset on successful connect

        inner loop:
            RetrieveResult → encode → broadcast frame
            (exits if camera.IsGrabbing() returns False or GenericException raised)

    except GenericException:
        log.warning("Camera error: %s — retrying in %.0fs", exc, backoff)
    finally:
        self._connected = False
        hub.broadcast_status(False)
        camera.Close()  # safe even if Open() failed

    self._stop_event.wait(backoff)
    backoff = min(backoff * 2, 30.0)  # 1 → 2 → 4 → ... → 30s cap
```

New field `_connected: bool` (guarded by `_raw_lock`). New `is_connected: bool` property.

## Section 2: WebSocket Status Messages

### `hub.py`

Queue type changes from `asyncio.Queue[bytes]` to `asyncio.Queue[bytes | str]`.

New method:
```python
def broadcast_status(self, connected: bool) -> None:
    msg = '{"type":"status","connected":true}' if connected else '{"type":"status","connected":false}'
    # same call_soon_threadsafe fan-out as broadcast()
```

### `server.py`

Stream handler checks item type:
```python
item = await asyncio.wait_for(q.get(), timeout=5.0)
if isinstance(item, bytes):
    await ws.send_bytes(item)
else:
    await ws.send_str(item)
```

### `viewer.html`

JS distinguishes binary frames from text status messages:
```js
ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
        // existing frame display logic
    } else {
        const msg = JSON.parse(e.data);
        if (msg.type === "status") {
            overlay.style.display = msg.connected ? "none" : "flex";
        }
    }
};
```

A semi-transparent "Camera disconnected" overlay sits over the frozen last frame (or blank canvas if never connected). It disappears automatically when the camera reconnects.

## Section 3: CLI Subcommands (`__main__.py`)

`argparse` dispatcher replaces the current bare `main()`:

```
basler-daemon run        # foreground mode (existing behaviour)
basler-daemon install    # register OS service + enable autostart
basler-daemon uninstall  # remove service
basler-daemon start      # start service immediately (after install)
basler-daemon stop       # stop service immediately
```

`run` is the default if no subcommand is given, preserving backwards compatibility.

## Section 4: OS Service (`service_manager.py`)

Single module with platform-dispatched functions: `install()`, `uninstall()`, `start()`, `stop()`.

### macOS (launchd)

- `install()`: writes `~/Library/LaunchAgents/com.basler.daemon.plist`, then `launchctl load <plist>`
- `uninstall()`: `launchctl unload <plist>`, deletes the file
- `start()` / `stop()`: `launchctl start/stop com.basler.daemon`

Plist settings:
```xml
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>~/Library/Logs/basler-daemon.log</string>
<key>StandardErrorPath</key><string>~/Library/Logs/basler-daemon.log</string>
```

`KeepAlive = true` means launchd itself handles crash recovery — the reconnection loop in `CameraService` handles camera-level recovery within a running process.

### Windows (pywin32)

- `BaslerDaemonService(win32serviceutil.ServiceFramework)` class in `service_manager.py`
  - `SvcDoRun`: calls `web.run_app()` with the aiohttp app
  - `SvcStop`: triggers graceful aiohttp shutdown
- `install()`: `win32serviceutil.InstallService(BaslerDaemonService, ..., startType=win32service.SERVICE_AUTO_START)`
- `uninstall()`: `win32serviceutil.RemoveService(...)`
- `start()` / `stop()`: `win32serviceutil.StartService(...)` / stop via service control

### Dependency

```toml
"pywin32; sys_platform == 'win32'",
```

Added to `[project.dependencies]` — installed automatically on Windows, ignored on macOS.

## Testing Strategy

No new unit tests for service registration (OS-specific infrastructure). The existing test suite (`test_config`, `test_encoding`, `test_hub`) remains valid. Manual verification:

- macOS: `basler-daemon install` → check plist exists → reboot → verify process running
- Windows: `basler-daemon install` → check Services panel → reboot → verify
- Reconnection: unplug/replug camera → verify viewer overlay appears/disappears
