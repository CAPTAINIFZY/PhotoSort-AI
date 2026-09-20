"""
ai/faces.py — Face detection using MediaPipe Tasks FaceDetector (mp 0.10.x+).

Uses the bundled blaze_face_short_range.task model.
The model path is read from MODEL_CACHE_DIR env var (default: models/).
"""

from __future__ import annotations

import os
from pathlib import Path
import cv2
import numpy as np

_MAX_ANALYSIS_DIM = 1024
_DETECTOR = None

def _model_path() -> str:
    cache = os.getenv("MODEL_CACHE_DIR")
    if not cache or not os.path.isdir(cache):
        cache = str(Path(__file__).resolve().parent.parent.parent / "models")
    return os.path.join(cache, "blaze_face_short_range.tflite")


def _get_detector():
    global _DETECTOR
    if _DETECTOR is None:
        import mediapipe as mp
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe.tasks import python as mp_tasks

        model_path = _model_path()
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"Face detection model not found at {model_path}. "
                "Download blaze_face_short_range.task from "
                "https://storage.googleapis.com/mediapipe-models/face_detector/"
                "blaze_face_short_range/float16/1/blaze_face_short_range.task"
            )

        base_opts = mp_tasks.BaseOptions(model_asset_path=model_path)
        opts = mp_vision.FaceDetectorOptions(
            base_options=base_opts,
            min_detection_confidence=0.4,
        )
        _DETECTOR = mp_vision.FaceDetector.create_from_options(opts)
    return _DETECTOR


def detect_faces(image_path: str) -> list[dict]:
    """
    Detect faces using MediaPipe Tasks FaceDetector.

    Returns list of {"bbox": [x, y, w, h], "confidence": float}.
    Empty list if no faces found.
    """
    import mediapipe as mp

    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise ValueError(f"Cannot open image: {image_path}")

    h, w = img_bgr.shape[:2]
    scale = 1.0
    if max(h, w) > _MAX_ANALYSIS_DIM:
        scale = _MAX_ANALYSIS_DIM / max(h, w)
        img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_AREA)
        h, w = img_bgr.shape[:2]

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)

    detector = _get_detector()
    result   = detector.detect(mp_image)

    faces: list[dict] = []
    if not result.detections:
        return faces

    inv = 1.0 / scale
    for det in result.detections:
        bb = det.bounding_box
        score = det.categories[0].score if det.categories else 0.0
        faces.append({
            "bbox": [
                int(bb.origin_x * inv),
                int(bb.origin_y * inv),
                int(bb.width    * inv),
                int(bb.height   * inv),
            ],
            "confidence": round(float(score), 4),
        })
    return faces
