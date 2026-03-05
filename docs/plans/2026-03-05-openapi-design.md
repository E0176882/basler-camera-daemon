# OpenAPI Documentation & Port Hardening Design

**Date:** 2026-03-05
**Status:** Approved

## Context

The daemon is deployed as a Windows EXE to a fixed device where access is always local. A static OpenAPI 3.1.0 spec is needed so an internal product can integrate against the API. Because the deployment target never changes, the host/port env vars add unnecessary complexity — the port is also changed to 47420 to avoid clashing with common services.

## Changes

| File | Change |
|---|---|
| `docs/openapi.yaml` | NEW — OpenAPI 3.1.0 spec for `/health`, `/stream`, `/capture` |
| `src/basler_camera_daemon/config.py` | Default port 8082 → 47420; remove `BASLER_PORT` env var |
| `src/basler_camera_daemon/__main__.py` | Remove `BASLER_HOST` env var; hardcode `127.0.0.1` |
| `README.md` | Update port references; remove `BASLER_HOST` / `BASLER_PORT` from env var table |

## Section 1: OpenAPI document

**File:** `docs/openapi.yaml`
**Version:** OpenAPI 3.1.0

Server block:
```yaml
servers:
  - url: http://127.0.0.1:47420
    description: Local daemon (default)
```

### Endpoints

#### `GET /health`
Returns camera status and model name.

- **200** `application/json`
  ```json
  {"status": "ok", "model": "acA2040-90uc"}
  ```
  Schema: `status` (string, enum `["ok"]`), `model` (string)

#### `GET /stream`
WebSocket upgrade — binary JPEG frames and JSON status messages.

Documented as GET with `101 Switching Protocols` response. Description covers both server-sent message types:
- **Binary** — raw JPEG frame bytes at the camera's native rate; slow clients silently drop frames (queue depth = 1)
- **Text** — `{"type":"status","connected":true|false}` — sent immediately on connect and whenever camera connects/disconnects

#### `POST /capture`
Single high-quality JPEG (quality 92) as base64. No disk write.

- **200** `application/json`
  ```json
  {"image_base64": "<base64-encoded JPEG>"}
  ```
- **503** `application/json` — no frame grabbed yet
  ```json
  {"error": "no frame available"}
  ```

## Section 2: Code changes

### `config.py`

- Default `port` field: `8082` → `47420`
- `from_env()`: remove `BASLER_PORT` lookup; `port` is no longer env-configurable
- Keep `BASLER_AUTO_EXPOSURE_MAX_US` (camera tuning, legitimately variable)

### `__main__.py`

- Remove `host = os.environ.get("BASLER_HOST", "127.0.0.1")`
- Replace with `host = "127.0.0.1"` (literal constant)

### `README.md`

- Replace all `8082` references with `47420`
- Remove `BASLER_HOST` and `BASLER_PORT` rows from the env var table
- Keep `BASLER_AUTO_EXPOSURE_MAX_US`

## Testing

No new tests needed. Existing `test_config.py` will need the port default assertion updated from `8082` to `47420`.
