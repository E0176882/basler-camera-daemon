from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from basler_camera_daemon.config import CameraConfig
from basler_camera_daemon.encoding import ImageEncoder
from basler_camera_daemon.mock_camera import MockCameraService


@pytest.fixture
def config() -> CameraConfig:
    return CameraConfig(
        port=47420, auto_exposure_max_us=10000, stream_quality=75, capture_quality=92
    )


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
