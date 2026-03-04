from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from pypylon import pylon  # type: ignore[import-untyped, unused-ignore]

from .config import CameraConfig
from .encoding import ImageEncoder
from .hub import FrameHub

log = logging.getLogger(__name__)

# The converter always outputs RGB8packed. For Mono8 cameras this replicates
# the single channel into all three, producing a (H, W, 3) array.
_PIXEL_FORMAT_PREFERENCE = ["BayerRG8", "BayerGB8", "BayerGR8", "BayerBG8", "RGB8", "BGR8", "Mono8"]


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
        self._raw_lock = threading.Lock()
        self._model_name = "unknown"
        self._latest_raw: np.ndarray[Any, np.dtype[Any]] | None = None
        self._connected = False

    @property
    def model_name(self) -> str:
        with self._raw_lock:
            return self._model_name

    @property
    def is_connected(self) -> bool:
        with self._raw_lock:
            return self._connected

    def get_latest_raw(self) -> np.ndarray[Any, np.dtype[Any]] | None:
        # Returns a copy of the most recently grabbed frame.
        # The copy is owned by Python; callers may read it safely after this call returns.
        with self._raw_lock:
            return self._latest_raw

    def start(self) -> None:
        self._thread = threading.Thread(target=self._grab_loop, daemon=True, name="camera")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                log.error("Camera thread did not stop within 5 s")

    def _configure(self, camera: pylon.InstantCamera) -> None:
        cam = camera.GetNodeMap()

        for name, value in [
            ("ExposureAuto", "Continuous"),
            ("GainAuto", "Continuous"),
            ("BalanceWhiteAuto", "Once"),
        ]:
            try:
                cam.GetNode(name).SetValue(value)
            except Exception as exc:
                log.warning("%s not available: %s", name, exc)

        try:
            upper = cam.GetNode("AutoExposureTimeUpperLimit")
            limit = min(self._config.auto_exposure_max_us, int(upper.GetMax()))
            upper.SetValue(limit)
            log.info("AutoExposureTimeUpperLimit = %d µs", limit)
        except Exception as exc:
            log.warning("AutoExposureTimeUpperLimit not available: %s", exc)

        for dim in ("Width", "Height"):
            try:
                node = cam.GetNode(dim)
                node.SetValue(node.GetMax())
            except Exception as exc:
                log.warning("%s max not settable: %s", dim, exc)

        try:
            pf_node = cam.GetNode("PixelFormat")
            available = pf_node.GetSymbolics()
            for fmt in _PIXEL_FORMAT_PREFERENCE:
                if fmt in available:
                    pf_node.SetValue(fmt)
                    log.info("PixelFormat = %s", fmt)
                    break
        except Exception as exc:
            log.warning("PixelFormat not configurable: %s", exc)

    def _grab_loop(self) -> None:
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_RGB8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

        backoff = 1.0
        while not self._stop_event.is_set():
            camera: pylon.InstantCamera | None = None
            try:
                camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
                camera.Open()
                with self._raw_lock:
                    self._model_name = camera.GetDeviceInfo().GetModelName()
                    self._connected = True
                self._hub.broadcast_status(True)
                log.info("Camera opened: %s", self._model_name)
                backoff = 1.0  # reset on successful connect

                self._configure(camera)
                camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                log.info("Grab loop started")

                while not self._stop_event.is_set() and camera.IsGrabbing():
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
                            arr: np.ndarray[Any, np.dtype[Any]] = rgb.GetArray()
                            jpeg = self._encoder.encode(arr, self._config.stream_quality)
                            with self._raw_lock:
                                self._latest_raw = arr.copy()
                            self._hub.broadcast(jpeg)
                        else:
                            log.warning("Grab failed: %s", grab.ErrorDescription)
                    finally:
                        grab.Release()

            except pylon.GenericException as exc:
                log.warning("Camera error: %s \u2014 retrying in %.0f s", exc, backoff)
            finally:
                with self._raw_lock:
                    was_connected = self._connected
                    self._connected = False
                if was_connected:
                    self._hub.broadcast_status(False)
                if camera is not None:
                    try:
                        camera.StopGrabbing()
                        camera.Close()
                    except Exception:
                        pass
                    log.info("Camera closed")

            if not self._stop_event.is_set():
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
