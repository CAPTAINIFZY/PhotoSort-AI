"""
ai/eyes.py — Closed-eye detection using MediaPipe Tasks FaceLandmarker + EAR.

Eye Aspect Ratio (EAR):
    EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)

Model: face_landmarker.task from mediapipe-models storage bucket.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import cv2

EAR_THRESHOLD = 0.2

# FaceLandmarker landmark indices for left/right eye (6-point EAR contour)
# These match the MediaPipe canonical face model.
_LEFT_EYE  = [362, 385, 387, 263, 373, 380]
_RIGHT_EYE = [33,  160, 158, 133, 153, 144]

_MAX_ANALYSIS_DIM = 1024
_LANDMARKER = None


def _model_path() -> str:
    cache = os.getenv("MODEL_CACHE_DIR")
    if not cache or not os.path.isdir(cache):
        cache = str(Path(__file__).resolve().parent.parent.parent / "models")
    return os.path.join(cache, "face_landmarker.task")


def _get_landmarker():
    global _LANDMARKER
    if _LANDMARKER is None:
        import mediapipe as mp
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe.tasks import python as mp_tasks

        model_path = _model_path()
        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"Face landmarker model not found at {model_path}. "
                "Download face_landmarker.task from "
                "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                "face_landmarker/float16/1/face_landmarker.task"
            )

        base_opts = mp_tasks.BaseOptions(model_asset_path=model_path)
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=base_opts,
            num_faces=20,
            min_face_detection_confidence=0.4,
            min_face_presence_confidence=0.4,
            min_tracking_confidence=0.4,
        )
        _LANDMARKER = mp_vision.FaceLandmarker.create_from_options(opts)
    return _LANDMARKER


def _ear(landmarks, indices: list[int], iw: int, ih: int) -> float:
    pts = [(landmarks[i].x * iw, landmarks[i].y * ih) for i in indices]
    def dist(a, b): return math.hypot(a[0]-b[0], a[1]-b[1])
    v1 = dist(pts[1], pts[5])
    v2 = dist(pts[2], pts[4])
    h  = dist(pts[0], pts[3])
    return 0.0 if h < 1e-6 else (v1 + v2) / (2.0 * h)


def detect_eye_state(image_path: str, face_bboxes: list) -> dict:
    """
    Use FaceLandmarker to compute EAR and detect closed eyes.

    Returns {"faces_checked": int, "possible_closed_eyes_count": int}.
    Returns zeroed dict immediately if face_bboxes is empty.
    """
    if not face_bboxes:
        return {"faces_checked": 0, "possible_closed_eyes_count": 0}

    import mediapipe as mp

    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        raise ValueError(f"Cannot open image: {image_path}")

    h, w = img_bgr.shape[:2]
    if max(h, w) > _MAX_ANALYSIS_DIM:
        scale = _MAX_ANALYSIS_DIM / max(h, w)
        img_bgr = cv2.resize(img_bgr, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_AREA)
        h, w = img_bgr.shape[:2]

    img_rgb  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)

    landmarker = _get_landmarker()
    result     = landmarker.detect(mp_image)

    if not result.face_landmarks:
        return {"faces_checked": 0, "possible_closed_eyes_count": 0}

    faces_checked = 0
    closed_count  = 0
    for face_lm in result.face_landmarks:
        left_ear  = _ear(face_lm, _LEFT_EYE,  w, h)
        right_ear = _ear(face_lm, _RIGHT_EYE, w, h)
        avg_ear   = (left_ear + right_ear) / 2.0
        faces_checked += 1
        if avg_ear < EAR_THRESHOLD:
            closed_count += 1

    return {"faces_checked": faces_checked, "possible_closed_eyes_count": closed_count}
