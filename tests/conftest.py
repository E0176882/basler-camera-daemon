from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def rgb_frame() -> np.ndarray:
    """4×4 black RGB frame for testing. No camera hardware required."""
    return np.zeros((4, 4, 3), dtype=np.uint8)
