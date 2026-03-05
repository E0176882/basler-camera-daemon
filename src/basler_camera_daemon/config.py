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
