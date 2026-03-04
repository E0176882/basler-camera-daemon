# Basler Camera Daemon

A minimal Python daemon that owns a Basler camera for its lifetime and exposes a localhost HTTP + WebSocket API. Built with `pypylon` (Basler's official binding) and `aiohttp`.

## Prerequisites

### Pylon SDK (required on all platforms)

Install the [Basler pylon SDK](https://www.baslerweb.com/en/software/pylon/) **before** installing `pypylon`.

| Platform | SDK location after install |
|----------|---------------------------|
| macOS    | `/Library/Frameworks/pylon.framework/` |
| Windows  | Added to `PATH` by the installer (default: `C:\Program Files\Basler\pylon 7\`) |

`pypylon` finds the SDK at runtime via the system framework / DLL path — no manual configuration needed.

### Python

Python 3.13 or newer.

## Installation

Requires Python 3.13+ and the Basler pylon SDK (macOS/Linux only — Windows users run the pre-built exe from [GitHub Releases](../../releases)).

```bash
pip install -e ".[dev]"
```

## Running

```bash
basler-daemon
# or
python -m basler_camera_daemon
```

Optional environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BASLER_HOST` | `127.0.0.1` | Bind address |
| `BASLER_PORT` | `8082` | Listening port |
| `BASLER_AUTO_EXPOSURE_MAX_US` | `10000` | Auto-exposure upper limit (µs) |

## API

### `GET /` — Browser viewer

Open `http://127.0.0.1:8082` in a browser to see the live stream. The page shows:
- Live JPEG frames via WebSocket (connection status indicator)
- Camera model from `/health`
- **Capture** button — grabs a quality-92 frame and displays it alongside the stream

### `GET /health`

Returns camera status and model name.

```bash
curl http://127.0.0.1:8082/health
```

```json
{"status": "ok", "model": "acA2040-90uc"}
```

### `GET /stream` (WebSocket)

Binary JPEG frames at the camera's native rate. Slow clients silently drop frames (queue depth = 1).

```bash
# Using wscat
wscat -b ws://127.0.0.1:8082/stream
```

In a browser:

```js
const ws = new WebSocket("ws://127.0.0.1:8082/stream");
ws.binaryType = "arraybuffer";
ws.onmessage = (e) => {
  const blob = new Blob([e.data], { type: "image/jpeg" });
  document.getElementById("img").src = URL.createObjectURL(blob);
};
```

### `POST /capture`

Returns a single high-quality JPEG (quality 92) as base64. No disk write.

```bash
curl -s -X POST http://127.0.0.1:8082/capture \
  | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
open('capture.jpg', 'wb').write(base64.b64decode(d['image_base64']))
print('Saved capture.jpg')
"
```

Returns `503` if no frame has been grabbed yet.

## Auto-configuration

On open the daemon applies:

| Setting | Value |
|---------|-------|
| ExposureAuto | Continuous |
| AutoExposureTimeUpperLimit | min(`BASLER_AUTO_EXPOSURE_MAX_US`, camera max) |
| GainAuto | Continuous |
| BalanceWhiteAuto | Once |
| Width / Height | Maximum supported |
| PixelFormat | BayerRG8 → BayerGB8 → RGB8 → Mono8 (first available) |

The pypylon `ImageFormatConverter` handles Bayer → RGB8 conversion before JPEG encoding.

## Graceful shutdown

`Ctrl-C` (SIGINT) or `SIGTERM` → aiohttp triggers `on_shutdown` → sets stop flag → camera grab loop exits → camera closed.

## Troubleshooting

**`NoneType` on `CreateFirstDevice`** — no camera detected. Check USB/GigE connection and that pylon Viewer can see the device.

**`ImportError: cannot import name 'pylon'`** — pypylon installed but pylon SDK not found. Verify SDK is installed at the expected path and re-install pypylon after the SDK.

**macOS: `Framework not found pylon`** — re-run the pylon SDK installer and ensure `/Library/Frameworks/pylon.framework` exists.

**Windows: DLL load failed** — ensure the pylon SDK installer ran and the pylon bin directory is on `PATH`. Reboot if needed.
