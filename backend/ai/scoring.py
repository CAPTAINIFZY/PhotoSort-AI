"""
ai/scoring.py — Scoring engine & recommendation logic for PhotoSort AI.

Computes:
1. Face score (size, clarity, eye-state penalties).
2. Uniqueness score (singleton vs. similarity cluster decay with AI Pick bonus).
3. Final composite score (weighted sum of 5 pillars minus blur, closed-eye, and duplicate penalties).
4. Recommendation ("keep", "review", "discard") and deterministic rationale.

All weights are retrieved dynamically from config.get_weights().
"""

from __future__ import annotations

import math
from typing import Optional

from config import get_weights

def get_recommendation_thresholds(weights: Optional[dict] = None) -> dict[str, float]:
    """Retrieve thresholds dynamically from scoring_weights.json or default to 75 / 50."""
    if weights is None:
        weights = get_weights()
    th = weights.get("thresholds", {}) if isinstance(weights, dict) else {}
    keep_th = th.get("keep", weights.get("keep_threshold", 75.0) if isinstance(weights, dict) else 75.0)
    review_th = th.get("review", weights.get("review_threshold", 50.0) if isinstance(weights, dict) else 50.0)
    return {"keep": float(keep_th), "review": float(review_th)}

RECOMMENDATION_THRESHOLDS = get_recommendation_thresholds()


# ── 1. Face Score ─────────────────────────────────────────────────────────────

def calculate_face_score(
    face_count: int,
    face_bboxes: Optional[list[dict]],
    closed_eyes_count: int = 0,
) -> float:
    """
    Compute face quality score (0-100).

    - 0 faces: returns neutral 60.0 (non-portrait images are not penalized).
    - >0 faces: base score scaled by average face scale, penalized by closed eyes ratio.
    """
    if face_count <= 0 or not face_bboxes:
        return 60.0

    valid_boxes = [f["bbox"] for f in face_bboxes if "bbox" in f and len(f["bbox"]) == 4]
    if not valid_boxes:
        return 60.0

    # Calculate average face dimension (sqrt(w * h))
    avg_dim = sum(math.sqrt(max(0, b[2]) * max(0, b[3])) for b in valid_boxes) / len(valid_boxes)

    # Scale base score: 65 for small faces (<40px), up to 92 for clear portraits (>150px)
    scale_factor = min(1.0, max(0.0, (avg_dim - 40.0) / 140.0))
    base_score = 68.0 + (scale_factor * 24.0)

    # Eye state penalty: scale up to 40 points if all faces have closed eyes
    closed_ratio = min(1.0, max(0.0, closed_eyes_count / float(face_count)))
    eye_penalty = closed_ratio * 40.0

    final_face_score = base_score - eye_penalty
    return round(max(0.0, min(100.0, final_face_score)), 2)


# ── 2. Uniqueness Score ───────────────────────────────────────────────────────

def calculate_uniqueness_score(
    similarity_group: Optional[int],
    cluster_size: int,
    is_ai_pick: bool,
) -> float:
    """
    Compute uniqueness score (0-100).

    - No cluster (singletons): 100.0.
    - Cluster members: 100.0 / cluster_size.
    - is_ai_pick receives a half-decay bonus since it's the intended keeper.
    """
    if similarity_group is None or cluster_size <= 1:
        return 100.0

    base_score = 100.0 / float(cluster_size)

    if is_ai_pick:
        # Half decay bonus: keeper remains high-scoring
        # For cluster of 2: 75; cluster of 4: 62.5; cluster of 10: 55
        ai_pick_score = 100.0 * (0.5 + (0.5 / float(cluster_size)))
        return round(max(0.0, min(100.0, ai_pick_score)), 2)

    return round(max(0.0, min(100.0, base_score)), 2)


# ── 3. Normalization Helpers ──────────────────────────────────────────────────

def normalize_sharpness(raw_sharpness: Optional[float]) -> float:
    """
    Normalize raw Laplacian variance to a [0, 100] scale.

    Laplacian variance benchmarks:
    - 0 to 40: blurry / out of focus
    - 50 to 180: acceptable handheld focus
    - 250+: sharp details
    """
    if raw_sharpness is None or raw_sharpness < 0:
        return 50.0  # neutral midpoint for missing data
    return round(min(100.0, max(0.0, (raw_sharpness / 250.0) * 100.0)), 2)


def normalize_exposure(exposure_data: Optional[dict]) -> float:
    """
    Normalize exposure metrics into a [0, 100] quality score.

    Evaluates:
    - Mean brightness distance from ideal neutral center (128).
    - Shadow clipping penalty (crushed blacks).
    - Highlight clipping penalty (blown highlights).
    """
    if not exposure_data:
        return 50.0

    mean_brightness = exposure_data.get("mean_brightness")
    if mean_brightness is None:
        mean_brightness = 128.0

    clipped_shadows = exposure_data.get("clipped_shadows_pct", 0.0) or 0.0
    clipped_highlights = exposure_data.get("clipped_highlights_pct", 0.0) or 0.0

    # Distance from ideal brightness of 128
    dist = abs(float(mean_brightness) - 128.0) / 128.0  # 0 at 128, 1 at 0 or 255
    brightness_score = 100.0 * (1.0 - (dist * 0.75))

    # Clipping deductions (up to 25 pts each)
    shadow_deduction = min(25.0, float(clipped_shadows) * 2.5)
    highlight_deduction = min(25.0, float(clipped_highlights) * 2.5)

    exposure_score = brightness_score - shadow_deduction - highlight_deduction
    return round(max(0.0, min(100.0, exposure_score)), 2)


# ── 4. Final Composite Score ──────────────────────────────────────────────────

def calculate_final_score(
    sharpness: Optional[float],
    exposure_data: Optional[dict],
    face_score: float,
    composition_score: float,
    uniqueness_score: float,
    duplicate: bool,
    weights: Optional[dict] = None,
    closed_eyes_count: int = 0,
    face_count: int = 0,
) -> float:
    """
    Calculate composite quality score (0-100) combining all 5 pillars minus penalties.

    Pulls all weights from config.get_weights() — never hardcoded.
    """
    if weights is None:
        weights = get_weights()

    norm_sharpness = normalize_sharpness(sharpness)
    norm_exposure  = normalize_exposure(exposure_data)

    # 1. Base weighted sum
    w_sharpness   = weights.get("sharpness", 0.25)
    w_exposure    = weights.get("exposure", 0.15)
    w_face        = weights.get("face_quality", 0.20)
    w_composition = weights.get("composition", 0.20)
    w_uniqueness  = weights.get("uniqueness", 0.20)

    score = (
        w_sharpness   * norm_sharpness
        + w_exposure    * norm_exposure
        + w_face        * face_score
        + w_composition * composition_score
        + w_uniqueness  * uniqueness_score
    )

    # 2. Penalty deductions
    # Blur penalty: activates when sharpness is low (<40)
    w_blur_pen = weights.get("blur_penalty", 0.30)
    if norm_sharpness < 40.0:
        blur_amount = ((40.0 - norm_sharpness) / 40.0) * 100.0
        score -= w_blur_pen * blur_amount

    # Closed eye penalty: scales with fraction of closed eyes
    w_closed_pen = weights.get("closed_eye_penalty", 0.20)
    if face_count > 0 and closed_eyes_count > 0:
        eye_ratio = min(1.0, closed_eyes_count / float(face_count))
        score -= w_closed_pen * (eye_ratio * 100.0)

    # Duplicate penalty: applies to duplicate frames
    w_dup_pen = weights.get("duplicate_penalty", 0.40)
    if duplicate:
        score -= w_dup_pen * 100.0

    return round(max(0.0, min(100.0, score)), 2)


# ── 5. Recommendation & Deterministic Rationale ───────────────────────────────

def generate_recommendation(
    score: float,
    duplicate: bool,
    is_ai_pick: bool,
    details: Optional[dict] = None,
    thresholds: Optional[dict[str, float]] = None,
) -> tuple[str, list[str]]:
    """
    Determine (recommendation, reasons) deterministically.

    Recommendations:
    - 'keep': score >= keep_threshold (default >= 75)
    - 'review': review_threshold <= score < keep_threshold (default 50-74),
                or duplicate non-picks with high score
    - 'reject': score < review_threshold (default < 50)
    """
    if thresholds is None:
        thresholds = get_recommendation_thresholds()

    details = details or {}
    norm_sharpness    = details.get("norm_sharpness", 50.0)
    norm_exposure     = details.get("norm_exposure", 50.0)
    face_score        = details.get("face_score", 60.0)
    composition_score = details.get("composition_score", 60.0)
    face_count        = details.get("face_count", 0)
    closed_eyes_count = details.get("closed_eyes_count", 0)
    comp_issues       = details.get("composition_issues", [])

    # Threshold classification
    keep_th = thresholds.get("keep", 75.0)
    review_th = thresholds.get("review", 50.0)

    if score >= keep_th:
        recommendation = "keep"
    elif score >= review_th:
        recommendation = "review"
    else:
        recommendation = "reject"

    # Non-representative members of a similarity cluster are forced to 'review' (never 'keep')
    if duplicate and not is_ai_pick:
        recommendation = "review"

    # Deterministic reasons list
    reasons: list[str] = []

    # Positive attributes
    if norm_sharpness >= 75.0:
        reasons.append("Sharp focus and crisp details")
    if norm_exposure >= 75.0:
        reasons.append("Well-balanced lighting and exposure")
    if composition_score >= 80.0:
        reasons.append("Strong rule-of-thirds composition")
    if face_count > 0 and closed_eyes_count == 0 and face_score >= 75.0:
        reasons.append("Clear facial expressions with open eyes")
    if is_ai_pick:
        reasons.append("Selected as AI Pick for similar frames")
    elif not duplicate and score >= 75.0:
        reasons.append("High overall quality shot")

    # Warnings / Negative attributes
    if norm_sharpness < 40.0:
        reasons.append("Soft focus or motion blur detected")
    if norm_exposure < 40.0:
        reasons.append("Sub-optimal exposure balance")
    if face_count > 0 and closed_eyes_count > 0:
        reasons.append(f"Possible closed eyes detected ({closed_eyes_count}/{face_count} faces)")
    for issue in comp_issues:
        if issue not in reasons:
            reasons.append(issue)
    if duplicate and not is_ai_pick:
        reasons.append("Duplicate frame in similarity cluster")

    # Fallback reason if empty
    if not reasons:
        if recommendation == "keep":
            reasons.append("Good overall composition and clarity")
        elif recommendation == "review":
            reasons.append("Moderate quality requiring user review")
        else:
            reasons.append("Low overall composite score")

    return recommendation, reasons
