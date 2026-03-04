from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraConfig:
    port: int = 8082
    auto_exposure_max_us: int = 10000
    stream_quality: int = 60
    capture_quality: int = 92

    @classmethod
    def from_env(cls) -> CameraConfig:
        return cls(
            port=int(os.environ.get("BASLER_PORT", 8082)),
            auto_exposure_max_us=int(os.environ.get("BASLER_AUTO_EXPOSURE_MAX_US", 10000)),
        )
