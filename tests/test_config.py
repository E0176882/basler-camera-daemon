import dataclasses

import pytest

from basler_camera_daemon.config import CameraConfig


def test_defaults(monkeypatch):
    monkeypatch.delenv("BASLER_PORT", raising=False)
    monkeypatch.delenv("BASLER_AUTO_EXPOSURE_MAX_US", raising=False)
    config = CameraConfig.from_env()
    assert config.port == 8082
    assert config.auto_exposure_max_us == 10000
    assert config.stream_quality == 60
    assert config.capture_quality == 92


def test_env_port_override(monkeypatch):
    monkeypatch.setenv("BASLER_PORT", "9000")
    config = CameraConfig.from_env()
    assert config.port == 9000


def test_env_exposure_override(monkeypatch):
    monkeypatch.setenv("BASLER_AUTO_EXPOSURE_MAX_US", "5000")
    config = CameraConfig.from_env()
    assert config.auto_exposure_max_us == 5000


def test_invalid_port_raises(monkeypatch):
    monkeypatch.setenv("BASLER_PORT", "not_a_number")
    with pytest.raises(ValueError):
        CameraConfig.from_env()


def test_config_is_immutable():
    config = CameraConfig.from_env()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.port = 1234  # type: ignore[misc]
