from __future__ import annotations

import io

import numpy as np
from PIL import Image


class ImageEncoder:
    def encode(self, arr: np.ndarray, quality: int) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
