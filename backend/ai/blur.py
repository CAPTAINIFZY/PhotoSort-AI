"""
ai/blur.py — Sharpness detection via Laplacian variance.

Laplacian variance is a standard, fast focus-quality metric:
  - High variance → sharp edges → well-focused image.
  - Low variance  → smooth/blurry → out-of-focus or motion-blurred.

No thresholding is done here; the caller (pipeline or scoring engine)
decides what constitutes "too blurry" for a given event type.
"""

from __future__ import annotations

import cv2
import numpy as np


# Working resolution cap: resize longest edge to this before analysis.
# Keeps analysis fast on large originals while preserving enough edge detail.
_MAX_ANALYSIS_DIM = 1024


def _load_gray(image_path: str) -> np.ndarray:
    """Load an image as grayscale, resizing if larger than _MAX_ANALYSIS_DIM."""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Cannot open image: {image_path}")

    h, w = img.shape
    if max(h, w) > _MAX_ANALYSIS_DIM:
        scale = _MAX_ANALYSIS_DIM / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return img


def calculate_sharpness(image_path: str) -> float:
    """
    Compute the Laplacian variance of the image as a sharpness proxy.

    Parameters
    ----------
    image_path : str
        Absolute path to the image file (any format OpenCV can decode).

    Returns
    -------
    float
        Raw Laplacian variance.  Higher → sharper.
        Typical ranges: < 50 blurry, 50–200 acceptable, > 200 sharp
        (these are heuristic and scene-dependent).

    Raises
    ------
    ValueError
        If the image cannot be opened by OpenCV.
    """
    img = _load_gray(image_path)
    laplacian = cv2.Laplacian(img, cv2.CV_64F)
    variance = float(laplacian.var())
    return variance
