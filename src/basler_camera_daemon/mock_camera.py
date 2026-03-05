from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

log = logging.getLogger(__name__)

# Classic SMPTE 75% color bars (8 bands, RGB values)
_SMPTE_COLORS: list[tuple[int, int, int]] = [
    (235, 235, 235),  # White
    (235, 235, 16),  # Yellow
    (16, 235, 235),  # Cyan
    (16, 235, 16),  # Green
    (235, 16, 235),  # Magenta
    (235, 16, 16),  # Red
    (16, 16, 235),  # Blue
    (16, 16, 16),  # Black
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
        self._thread = threading.Thread(target=self._generate_loop, daemon=True, name="mock-camera")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log.error("Mock camera thread did not stop within 5 s")

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
                bbox = draw.textbbox((10, 10), ts)
                draw.rectangle((bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2), fill=(0, 0, 0))
                draw.text((10, 10), ts, fill=(255, 255, 255))
                arr: np.ndarray[Any, np.dtype[Any]] = np.array(img)
                jpeg = self._encoder.encode(arr, self._config.stream_quality)
                with self._lock:
                    self._latest_raw = arr.copy()
                self._hub.broadcast(jpeg)
                self._stop_event.wait(1.0 / _FPS)
        finally:
            with self._lock:
                self._connected = False
            self._hub.broadcast_status(False)
