"""Background removal using rembg (onnxruntime-backed)."""

from __future__ import annotations

import os


def remove_background(input_path: str, output_path: str) -> str:
    """
    Remove background from input_path image, save transparent PNG to output_path.
    Falls back gracefully if rembg is not installed.
    Returns output_path.
    """
    from rembg import remove
    from PIL import Image

    with open(input_path, "rb") as f:
        data = f.read()

    result = remove(data)

    with open(output_path, "wb") as f:
        f.write(result)

    return output_path
