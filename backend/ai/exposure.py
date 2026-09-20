"""
ai/exposure.py — Exposure quality analysis via grayscale histogram.

Returns three complementary metrics that together characterise the
tonal distribution of the image:

  mean_brightness         — overall lightness (0 = black, 255 = white)
  clipped_shadows_pct     — fraction of pixels crushed to near-black (≤ 5)
  clipped_highlights_pct  — fraction of pixels blown to near-white (≥ 250)

Well-exposed images typically have:
  50 < mean_brightness < 200, shadows_pct < 5 %, highlights_pct < 5 %.
"""

from __future__ import annotations

import cv2
import numpy as np

_MAX_ANALYSIS_DIM = 1024

# Pixel-value thresholds for "clipped" shadows / highlights
_SHADOW_THRESHOLD    = 5    # pixels ≤ this are considered crushed black
_HIGHLIGHT_THRESHOLD = 250  # pixels ≥ this are considered blown white


def calculate_exposure(image_path: str) -> dict:
    """
    Compute grayscale exposure metrics for an image.

    Parameters
    ----------
    image_path : str
        Absolute path to the image file.

    Returns
    -------
    dict with keys:
        mean_brightness         : float  — [0, 255]
        clipped_shadows_pct     : float  — [0.0, 100.0]
        clipped_highlights_pct  : float  — [0.0, 100.0]

    Raises
    ------
    ValueError
        If the image cannot be opened.
    """
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Cannot open image: {image_path}")

    # Resize for speed
    h, w = img.shape
    if max(h, w) > _MAX_ANALYSIS_DIM:
        scale = _MAX_ANALYSIS_DIM / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)

    total_pixels = img.size

    # Compute 256-bin histogram in one call
    hist = cv2.calcHist([img], [0], None, [256], [0, 256]).flatten()

    mean_brightness        = float(np.average(np.arange(256), weights=hist))
    clipped_shadows_pct    = float(hist[:_SHADOW_THRESHOLD + 1].sum() / total_pixels * 100)
    clipped_highlights_pct = float(hist[_HIGHLIGHT_THRESHOLD:].sum()  / total_pixels * 100)

    return {
        "mean_brightness":        round(mean_brightness,        3),
        "clipped_shadows_pct":    round(clipped_shadows_pct,    4),
        "clipped_highlights_pct": round(clipped_highlights_pct, 4),
    }
