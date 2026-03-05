from __future__ import annotations

import io
from typing import Any

import numpy as np

from basler_camera_daemon.encoding import ImageEncoder


def _solid_frame(h: int = 4, w: int = 4) -> np.ndarray[Any, np.dtype[Any]]:
    """Return a small solid-colour RGB array."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _is_jpeg(data: bytes) -> bool:
    """Return True if data is a valid, decodable JPEG."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:
        return False


def test_encode_returns_bytes() -> None:
    encoder = ImageEncoder()
    result = encoder.encode(_solid_frame(), quality=60)
    assert isinstance(result, bytes)


def test_encode_produces_valid_jpeg() -> None:
    encoder = ImageEncoder()
    result = encoder.encode(_solid_frame(), quality=60)
    assert _is_jpeg(result)


def test_higher_quality_produces_larger_file() -> None:
    encoder = ImageEncoder()
    # Use a noisy image so compression ratio varies meaningfully with quality
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    low = encoder.encode(noisy, quality=10)
    high = encoder.encode(noisy, quality=95)
    assert len(high) > len(low)


def test_encode_various_resolutions() -> None:
    encoder = ImageEncoder()
    for h, w in [(4, 4), (64, 64), (480, 640)]:
        result = encoder.encode(_solid_frame(h, w), quality=60)
        assert _is_jpeg(result), f"Not a JPEG for {h}x{w}"
