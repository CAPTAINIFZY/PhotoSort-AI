"""
ai/pipeline.py — Per-image analysis orchestrator (Phase 3 + 4).

Two separate entry points:

  analyze_cv_signals(photo_id, image_path)
      Runs blur, exposure, face detection, and eye-state detection.
      Designed for use in ProcessPoolExecutor worker processes —
      only loads small OpenCV / MediaPipe models.

  analyze_embedding(photo_id, image_path)
      Runs CLIP embedding + category classification.
      Designed for sequential use in the main process so the large
      CLIP model (350 MB) is loaded exactly ONCE rather than once
      per worker process.

  analyze_image(photo_id, image_path)
      Convenience wrapper that calls both in sequence.
      Used for unit tests; not called by job_runner.py (which uses
      the split two-pass approach for performance).
"""

from __future__ import annotations

import traceback

from ai.blur     import calculate_sharpness
from ai.exposure import calculate_exposure
from ai.eyes     import detect_eye_state
from ai.faces    import detect_faces


# ── Pass 1: fast CV signals (runs in worker processes) ────────────────────────

def analyze_cv_signals(photo_id: str, image_path: str) -> dict:
    """
    Run blur, exposure, face detection, and eye-state detection.

    Each signal is wrapped in its own try/except so a failure in one
    module does not abort the others; missing signals are stored as None.

    Returns a dict suitable for update_photo_analysis() — does NOT
    include embedding or category (handled by analyze_embedding() in
    the main process).
    """
    import os
    import cv2

    result: dict = {
        "photo_id":                   photo_id,
        "sharpness_score":            None,
        "mean_brightness":            None,
        "clipped_shadows_pct":        None,
        "clipped_highlights_pct":     None,
        "face_count":                 None,
        "face_bboxes":                None,
        "closed_eyes_detected":       None,
        "possible_closed_eyes_count": None,
        "processing_error":           None,
    }

    # ── Sanity check ───────────────────────────────────────────────────────────
    if not os.path.isfile(image_path):
        result["processing_error"] = f"File not found: {image_path}"
        return result
    if cv2.imread(image_path, cv2.IMREAD_GRAYSCALE) is None:
        result["processing_error"] = f"Cannot open image: {image_path}"
        return result

    # ── 1. Sharpness ───────────────────────────────────────────────────────────
    try:
        result["sharpness_score"] = calculate_sharpness(image_path)
    except Exception:
        result["processing_error"] = (
            result["processing_error"]
            or f"sharpness failed: {traceback.format_exc(limit=1).strip()}"
        )

    # ── 2. Exposure ────────────────────────────────────────────────────────────
    try:
        exp = calculate_exposure(image_path)
        result["mean_brightness"]        = exp["mean_brightness"]
        result["clipped_shadows_pct"]    = exp["clipped_shadows_pct"]
        result["clipped_highlights_pct"] = exp["clipped_highlights_pct"]
    except Exception:
        pass

    # ── 3. Face detection ──────────────────────────────────────────────────────
    face_bboxes: list = []
    try:
        face_bboxes = detect_faces(image_path)
        result["face_count"]  = len(face_bboxes)
        result["face_bboxes"] = face_bboxes
    except Exception:
        pass

    # ── 4. Eye state ───────────────────────────────────────────────────────────
    try:
        eye = detect_eye_state(image_path, face_bboxes)
        closed_n = eye["possible_closed_eyes_count"]
        result["possible_closed_eyes_count"] = closed_n
        result["closed_eyes_detected"]        = closed_n > 0
    except Exception:
        pass

    return result


# ── Pass 2: CLIP embedding + classification (runs in main process) ─────────────

def analyze_embedding(photo_id: str, image_path: str) -> dict:
    """
    Generate a CLIP embedding and zero-shot category for one image.

    Returns:
        {
            "photo_id":  str,
            "embedding": np.ndarray | None,
            "category":  str | None,
        }

    Non-fatal: on any failure, embedding=None and category=None are
    returned so the photo is excluded from clustering without aborting
    the batch.
    """
    import os

    result: dict = {
        "photo_id":  photo_id,
        "embedding": None,
        "category":  None,
    }

    if not os.path.isfile(image_path):
        return result

    try:
        from ai.embeddings import generate_embedding
        from ai.classify   import classify_photo

        emb = generate_embedding(image_path)
        cat = classify_photo(emb)

        result["embedding"] = emb
        result["category"]  = cat
    except Exception:
        pass

    return result


# ── Combined (for unit tests / standalone use) ────────────────────────────────

def analyze_image(photo_id: str, image_path: str) -> dict:
    """
    Run both passes in sequence.  Convenience function for unit tests.
    job_runner.py uses analyze_cv_signals() + analyze_embedding() separately.
    """
    cv_result  = analyze_cv_signals(photo_id, image_path)
    emb_result = analyze_embedding(photo_id, image_path)
    return {**cv_result, **emb_result}
