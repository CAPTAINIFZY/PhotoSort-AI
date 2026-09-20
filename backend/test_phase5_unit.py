"""
test_phase5_unit.py — Unit tests for Phase 5 (Composition & Scoring Engine).
"""

from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image

# Ensure backend in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.composition import calculate_composition
from ai.scoring import (
    calculate_face_score,
    calculate_uniqueness_score,
    calculate_final_score,
    generate_recommendation,
    normalize_sharpness,
    normalize_exposure,
    RECOMMENDATION_THRESHOLDS,
)
from config import get_weights


def test_composition_rule_of_thirds():
    # Create test image 300x300
    tmp_path = Path(__file__).resolve().parent / "tmp_comp_test.jpg"
    Image.new("RGB", (300, 300), (200, 200, 200)).save(tmp_path)

    try:
        # Face placed near (100, 100) -> 1/3, 1/3 of 300x300
        # Bbox: x=65, y=65, w=70, h=70 -> centroid = (100, 100), area = 4900 (5.4% of 90000)
        face_rot = [{"bbox": [65, 65, 70, 70], "confidence": 0.95}]
        res_rot = calculate_composition(str(tmp_path), face_rot)
        assert res_rot["composition_score"] >= 85.0, f"Expected high RoT score, got {res_rot}"
        assert len(res_rot["issues"]) == 0

        # Face cropped at edge
        face_edge = [{"bbox": [0, 10, 40, 40], "confidence": 0.95}]
        res_edge = calculate_composition(str(tmp_path), face_edge)
        assert "Subject cropped at frame edge" in res_edge["issues"]
        assert res_edge["composition_score"] < res_rot["composition_score"]

        # Face too small (<5% of 300*300 = 4500 pixels; 10*10 = 100)
        face_small = [{"bbox": [95, 95, 10, 10], "confidence": 0.95}]
        res_small = calculate_composition(str(tmp_path), face_small)
        assert "Subject too small in frame" in res_small["issues"]

        # No faces fallback
        res_noface = calculate_composition(str(tmp_path), [])
        assert 0.0 <= res_noface["composition_score"] <= 100.0

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_face_score():
    # 0 faces -> neutral 60.0
    assert calculate_face_score(0, [], 0) == 60.0
    assert calculate_face_score(0, None, 0) == 60.0

    # 1 face, open eyes
    bboxes = [{"bbox": [100, 100, 150, 150], "confidence": 0.95}]
    score_open = calculate_face_score(1, bboxes, closed_eyes_count=0)
    assert score_open >= 80.0, f"Expected high score for clear face, got {score_open}"

    # 1 face, closed eyes
    score_closed = calculate_face_score(1, bboxes, closed_eyes_count=1)
    assert score_closed < score_open - 30.0, f"Expected eye penalty, got {score_closed} vs {score_open}"


def test_uniqueness_score():
    # Singletons get 100.0
    assert calculate_uniqueness_score(None, 1, False) == 100.0
    assert calculate_uniqueness_score(None, 0, False) == 100.0

    # Cluster of 4
    # Non-pick: 100 / 4 = 25.0
    score_non_pick = calculate_uniqueness_score(0, 4, is_ai_pick=False)
    assert score_non_pick == 25.0

    # AI Pick: half decay bonus = 100 * (0.5 + 0.5/4) = 62.5
    score_pick = calculate_uniqueness_score(0, 4, is_ai_pick=True)
    assert score_pick == 62.5
    assert score_pick > score_non_pick


def test_normalization():
    # Sharpness normalization: [0, 250] -> [0, 100]
    assert normalize_sharpness(0.0) == 0.0
    assert normalize_sharpness(125.0) == 50.0
    assert normalize_sharpness(250.0) == 100.0
    assert normalize_sharpness(500.0) == 100.0
    assert normalize_sharpness(None) == 50.0

    # Exposure normalization
    exp_perfect = {"mean_brightness": 128.0, "clipped_shadows_pct": 0.0, "clipped_highlights_pct": 0.0}
    assert normalize_exposure(exp_perfect) == 100.0

    exp_dark = {"mean_brightness": 20.0, "clipped_shadows_pct": 15.0, "clipped_highlights_pct": 0.0}
    assert normalize_exposure(exp_dark) < 50.0


def test_final_score_and_penalties():
    weights = get_weights()

    # High quality photo
    score_good = calculate_final_score(
        sharpness=220.0,
        exposure_data={"mean_brightness": 128.0, "clipped_shadows_pct": 0.0, "clipped_highlights_pct": 0.0},
        face_score=85.0,
        composition_score=90.0,
        uniqueness_score=100.0,
        duplicate=False,
        weights=weights,
        closed_eyes_count=0,
        face_count=1,
    )
    assert score_good >= 80.0, f"Expected high final score, got {score_good}"

    # Blurry photo
    score_blurry = calculate_final_score(
        sharpness=10.0,  # very blurry -> norm = 4.0 < 40 -> triggers blur penalty
        exposure_data={"mean_brightness": 128.0, "clipped_shadows_pct": 0.0, "clipped_highlights_pct": 0.0},
        face_score=85.0,
        composition_score=90.0,
        uniqueness_score=100.0,
        duplicate=False,
        weights=weights,
        closed_eyes_count=0,
        face_count=1,
    )
    assert score_blurry < score_good - 30.0

    # Duplicate penalty
    score_dup = calculate_final_score(
        sharpness=220.0,
        exposure_data={"mean_brightness": 128.0, "clipped_shadows_pct": 0.0, "clipped_highlights_pct": 0.0},
        face_score=85.0,
        composition_score=90.0,
        uniqueness_score=50.0,
        duplicate=True,
        weights=weights,
        closed_eyes_count=0,
        face_count=1,
    )
    # duplicate_penalty is 0.40 -> -40 pts
    assert score_dup < score_good - 35.0


def test_recommendation_and_reasons():
    # Score >= 75 -> keep
    rec, reasons = generate_recommendation(
        score=82.0,
        duplicate=False,
        is_ai_pick=False,
        details={"norm_sharpness": 85.0, "norm_exposure": 80.0, "composition_score": 85.0},
    )
    assert rec == "keep"
    assert "Sharp focus and crisp details" in reasons
    assert "Well-balanced lighting and exposure" in reasons

    # Force review for duplicates even if score is high
    rec_dup, reasons_dup = generate_recommendation(
        score=80.0,
        duplicate=True,
        is_ai_pick=False,
        details={"norm_sharpness": 85.0},
    )
    assert rec_dup == "review", f"Duplicates must be forced to 'review', got {rec_dup}"
    assert "Duplicate frame in similarity cluster" in reasons_dup

    # Score < 50 -> reject
    rec_bad, reasons_bad = generate_recommendation(
        score=35.0,
        duplicate=False,
        is_ai_pick=False,
        details={"norm_sharpness": 20.0},
    )
    assert rec_bad == "reject"
    assert "Soft focus or motion blur detected" in reasons_bad


if __name__ == "__main__":
    print("Running Phase 5 Unit Tests...")
    test_composition_rule_of_thirds()
    print("  [PASS] test_composition_rule_of_thirds")
    test_face_score()
    print("  [PASS] test_face_score")
    test_uniqueness_score()
    print("  [PASS] test_uniqueness_score")
    test_normalization()
    print("  [PASS] test_normalization")
    test_final_score_and_penalties()
    print("  [PASS] test_final_score_and_penalties")
    test_recommendation_and_reasons()
    print("  [PASS] test_recommendation_and_reasons")
    print("\nALL UNIT TESTS PASSED!")
