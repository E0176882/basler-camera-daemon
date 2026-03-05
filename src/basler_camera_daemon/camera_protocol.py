from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class CameraProtocol(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def is_connected(self) -> bool: ...

    def get_latest_raw(self) -> np.ndarray[Any, np.dtype[Any]] | None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
