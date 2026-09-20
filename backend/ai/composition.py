"""
ai/composition.py — Composition analysis for event photos.

Evaluates photo composition using:
1. Rule-of-Thirds Centroid Analysis (when faces are detected):
   - Computes centroid of largest subject face.
   - Evaluates proximity to the 4 rule-of-thirds power points.
   - Penalizes tight cropping at frame borders or subject occupying <5% of frame.
2. Quadrant Balance Heuristic (for face-less photos like details/landscapes):
   - Divides image into 4 quadrants.
   - Evaluates tonal and brightness balance across the frame.

Returns:
    {"composition_score": float (0-100), "issues": list[str]}
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


# Rule-of-thirds power points in normalized coordinates [0, 1]
_THIRD_POINTS = (
    (1.0 / 3.0, 1.0 / 3.0),
    (2.0 / 3.0, 1.0 / 3.0),
    (1.0 / 3.0, 2.0 / 3.0),
    (2.0 / 3.0, 2.0 / 3.0),
)
# Max distance in [0, 1]^2 to the nearest rule-of-thirds point is at (0,0): sqrt((1/3)^2 + (1/3)^2) = sqrt(2)/3
_MAX_DISTANCE = math.sqrt(2.0) / 3.0  # approx 0.4714


def calculate_composition(image_path: str, face_bboxes: Optional[list[dict]] = None) -> dict:
    """
    Evaluate the composition score (0-100) and identify potential composition issues.

    Parameters
    ----------
    image_path : str
        Path to the image file.
    face_bboxes : list[dict], optional
        List of face detections containing {"bbox": [x, y, w, h], ...}.

    Returns
    -------
    dict
        {
            "composition_score": float (0.0 to 100.0),
            "issues": list[str]
        }
    """
    issues: list[str] = []

    # Read image dimensions
    img = cv2.imread(image_path)
    if img is None:
        return {"composition_score": 50.0, "issues": ["Cannot open image for composition analysis"]}

    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return {"composition_score": 50.0, "issues": ["Invalid image dimensions"]}

    frame_area = float(w * h)

    # ── Branch A: Face-based Rule-of-Thirds Composition ──────────────────────────
    if face_bboxes and len(face_bboxes) > 0:
        # Filter valid bboxes
        valid_boxes = [f["bbox"] for f in face_bboxes if "bbox" in f and len(f["bbox"]) == 4]

        if valid_boxes:
            # Select largest face by area (w * h)
            largest_box = max(valid_boxes, key=lambda b: b[2] * b[3])
            bx, by, bw, bh = largest_box
            face_area = float(max(0, bw) * max(0, bh))
            face_pct = (face_area / frame_area) if frame_area > 0 else 0.0

            # Centroid of largest face
            cx = bx + bw / 2.0
            cy = by + bh / 2.0

            # Normalized centroid in [0, 1]
            nx = max(0.0, min(1.0, cx / w))
            ny = max(0.0, min(1.0, cy / h))

            # Minimum Euclidean distance to any of the 4 rule-of-thirds points
            min_dist = min(
                math.sqrt((nx - px) ** 2 + (ny - py) ** 2)
                for px, py in _THIRD_POINTS
            )

            # Base score: 100 at intersection point, decreasing with distance
            dist_factor = min(1.0, min_dist / _MAX_DISTANCE)
            score = 100.0 * (1.0 - (dist_factor * 0.65))  # Keep baseline >= 35 before penalties

            # Check for edge-cropping (border touch margin: within 2% of edge)
            margin_x = 0.02 * w
            margin_y = 0.02 * h
            touches_edge = (
                bx <= margin_x or
                by <= margin_y or
                (bx + bw) >= (w - margin_x) or
                (by + bh) >= (h - margin_y)
            )
            if touches_edge:
                score -= 25.0
                issues.append("Subject cropped at frame edge")

            # Check if subject is too small (<5% of frame area)
            if face_pct < 0.05:
                score -= 20.0
                issues.append("Subject too small in frame")
            elif face_pct > 0.65:
                # Excessively tight crop
                score -= 10.0
                issues.append("Tight crop on subject")

            # Check if subject is dead-center (distance to center (0.5, 0.5) < 0.06)
            center_dist = math.sqrt((nx - 0.5) ** 2 + (ny - 0.5) ** 2)
            if center_dist < 0.06 and min_dist > 0.15:
                score -= 5.0
                issues.append("Subject dead-center")

            return {
                "composition_score": round(max(0.0, min(100.0, score)), 2),
                "issues": issues,
            }

    # ── Branch B: Quadrant Balance Heuristic (No Faces) ──────────────────────────
    # Split frame into 4 quadrants to assess balance and lighting distribution
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mid_y, mid_x = h // 2, w // 2

    q_tl = gray[0:mid_y, 0:mid_x]
    q_tr = gray[0:mid_y, mid_x:w]
    q_bl = gray[mid_y:h, 0:mid_x]
    q_br = gray[mid_y:h, mid_x:w]

    # Calculate average brightness per quadrant
    means = [
        float(np.mean(q_tl)) if q_tl.size > 0 else 128.0,
        float(np.mean(q_tr)) if q_tr.size > 0 else 128.0,
        float(np.mean(q_bl)) if q_bl.size > 0 else 128.0,
        float(np.mean(q_br)) if q_br.size > 0 else 128.0,
    ]

    brightness_std = float(np.std(means))

    # Low standard deviation across quadrants indicates balanced lighting
    # Std dev of 0 -> 88 score, std dev of 60 -> ~45 score
    score = 88.0 - (brightness_std * 0.7)
    if brightness_std > 45.0:
        issues.append("Uneven lighting across frame")

    return {
        "composition_score": round(max(20.0, min(100.0, score)), 2),
        "issues": issues,
    }
