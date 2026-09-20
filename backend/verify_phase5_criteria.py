"""
verify_phase5_criteria.py — Comprehensive acceptance criteria verification for PhotoSort AI Phase 5.

Verifies:
1. Every photo has composition_score, face_score, uniqueness_score, and a final score (0–100)
2. recommendation and status are set (keep/review/reject) and match the configured thresholds
3. reasons is a non-empty, sensible list for every photo
4. Non-representative members of a similarity cluster are never status='keep' even with a high raw score
5. Changing a weight in config/scoring_weights.json and re-running scoring changes results without touching code
6. Phase 4's AI Pick per cluster is re-selected using final score (highest score wins, not just sharpness)
7. Photos with zero faces still get a sensible score (not null, not zero by default)
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db, update_photo_analysis
from config import get_weights, _WEIGHTS_PATH
from ai.composition import calculate_composition
from ai.scoring import (
    calculate_face_score,
    calculate_uniqueness_score,
    calculate_final_score,
    generate_recommendation,
    normalize_sharpness,
    normalize_exposure,
    get_recommendation_thresholds,
)
from ai.similarity import pick_cluster_representative
from workers.job_runner import score_batch, rescore_batch


def make_image(kind: str) -> Image.Image:
    """Generate deterministic synthetic test images."""
    img = Image.new("RGB", (300, 300), (240, 240, 240))
    d = ImageDraw.Draw(img)

    if kind == "portrait":
        # Sharp portrait near RoT intersection (100, 100)
        d.rectangle([0, 0, 300, 300], fill=(225, 225, 225))
        d.ellipse([65, 65, 135, 135], fill=(255, 220, 180))
        d.ellipse([80, 85, 90, 95], fill=(30, 30, 30))
        d.ellipse([110, 85, 120, 95], fill=(30, 30, 30))
        d.arc([85, 105, 115, 120], start=0, end=180, fill=(180, 40, 40), width=3)
        for i in range(12):
            d.line([10 + i * 22, 200, 20 + i * 22, 280], fill=(10, 10, 10), width=3)

    elif kind == "landscape":
        # Scenery with 0 faces
        d.rectangle([0, 0, 300, 150], fill=(135, 206, 235))
        d.rectangle([0, 150, 300, 300], fill=(34, 139, 34))
        d.ellipse([190, 30, 250, 90], fill=(255, 220, 0))

    elif kind == "blurry":
        # Low contrast wash
        d.rectangle([0, 0, 300, 300], fill=(170, 170, 170))
        d.ellipse([60, 60, 240, 240], fill=(165, 165, 165))

    elif kind == "cluster_a":
        # Sharp edges, but off-center / poor composition
        d.rectangle([0, 0, 300, 300], fill=(200, 200, 200))
        d.rectangle([5, 5, 60, 60], fill=(50, 50, 50))  # clipped at border
        for i in range(10):
            d.line([i * 30, 0, i * 30, 300], fill=(0, 0, 0), width=4)

    elif kind == "cluster_b":
        # Balanced, beautiful composition near (100, 100)
        d.rectangle([0, 0, 300, 300], fill=(230, 230, 230))
        d.rectangle([70, 70, 130, 130], fill=(70, 130, 180))
        d.ellipse([80, 80, 120, 120], fill=(255, 215, 0))

    return img


def setup_test_batch() -> tuple[str, dict[str, str]]:
    init_db()
    batch_id = f"verify_{uuid4().hex[:8]}"
    upload_dir = ROOT / "uploads" / "originals" / batch_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    items = {
        f"{batch_id}_portrait": ("portrait.jpg", make_image("portrait"), 260.0, 125.0, 1, [{"bbox": [65, 65, 70, 70]}], None, False),
        f"{batch_id}_landscape": ("landscape.jpg", make_image("landscape"), 180.0, 130.0, 0, [], None, False),
        f"{batch_id}_blurry": ("blurry.jpg", make_image("blurry"), 20.0, 120.0, 0, [], None, False),
        f"{batch_id}_cluster_1": ("cluster_1.jpg", make_image("cluster_a"), 280.0, 80.0, 0, [], 101, False), # sharper, but worse comp/exp
        f"{batch_id}_cluster_2": ("cluster_2.jpg", make_image("cluster_b"), 190.0, 128.0, 0, [], 101, True), # slightly less sharp, but great comp/exp
        f"{batch_id}_corrupt": ("corrupt.jpg", None, None, None, 0, [], None, False),
    }

    id_to_path: dict[str, str] = {}
    conn = sqlite3.connect(DB_PATH)

    for pid, (fname, img, sharp, bright, fcnt, bboxes, sg, is_dup) in items.items():
        fpath = str(upload_dir / fname)
        if img:
            img.save(fpath, "JPEG")
        else:
            with open(fpath, "wb") as f:
                f.write(b"not a valid image")

        id_to_path[pid] = fpath

        conn.execute(
            """INSERT INTO photos (
                id, filename, batch_id, sharpness_score, mean_brightness,
                clipped_shadows_pct, clipped_highlights_pct, face_count,
                face_bboxes, possible_closed_eyes_count, similarity_group,
                duplicate, processing_error, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid, fname, batch_id, sharp, bright,
                2.0 if bright else None, 1.0 if bright else None,
                fcnt, json.dumps(bboxes), 0, sg,
                1 if is_dup else 0,
                "Unreadable file" if img is None else None,
                "error" if img is None else "review",
            ),
        )

    conn.commit()
    conn.close()
    return batch_id, id_to_path


def run_all_checks():
    print("=" * 70)
    print("PHOTOSORT AI — PHASE 5 ACCEPTANCE CRITERIA VERIFICATION")
    print("=" * 70)

    batch_id, id_to_path = setup_test_batch()

    # Run scoring pass
    scored = score_batch(batch_id, id_to_path)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    photo_rows = conn.execute("SELECT * FROM photos WHERE batch_id = ?", (batch_id,)).fetchall()
    photos = {r["id"]: dict(r) for r in photo_rows}
    photos_by_name = {r["filename"]: dict(r) for r in photo_rows}
    conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 1:
    # "Every photo has composition_score, face_score, uniqueness_score, and a final score (0–100)"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 1] Scores exist and bounded (0-100)...")
    for pid, p in photos.items():
        for field in ("composition_score", "face_score", "uniqueness_score", "score"):
            val = p[field]
            assert val is not None, f"Photo {pid} has null {field}"
            assert 0.0 <= val <= 100.0, f"Photo {pid} {field}={val} out of bounds [0, 100]"
        print(f"  ✓ {p['filename']:15s} -> comp={p['composition_score']:.1f}, face={p['face_score']:.1f}, uniq={p['uniqueness_score']:.1f}, final={p['score']:.1f}")
    print("  --> PASS: Every photo has all 4 scores bounded in [0, 100].")

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 2:
    # "recommendation and status are set (keep/review/reject) and match the configured thresholds"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 2] Recommendation and status set (keep/review/reject) matching thresholds...")
    thresholds = get_recommendation_thresholds()
    keep_th = thresholds["keep"]
    review_th = thresholds["review"]

    for pid, p in photos.items():
        rec = p["recommendation"]
        stat = p["status"]

        assert rec in ("keep", "review", "reject"), f"Invalid recommendation '{rec}' for {pid}"
        if p["processing_error"]:
            assert stat in ("error", "reject"), f"Corrupt photo status is {stat}"
            assert rec == "reject"
        else:
            assert stat in ("keep", "review", "reject"), f"Invalid status '{stat}' for {pid}"
            assert stat == rec, f"Photo {pid} status '{stat}' != recommendation '{rec}'"

            # Check threshold logic
            if p["duplicate"]:
                assert rec == "review", f"Duplicate non-pick must be 'review', got {rec}"
            elif p["score"] >= keep_th:
                assert rec == "keep", f"Expected 'keep' for score {p['score']} >= {keep_th}, got {rec}"
            elif p["score"] < review_th:
                assert rec == "reject", f"Expected 'reject' for score {p['score']} < {review_th}, got {rec}"
            elif review_th <= p["score"] < keep_th:
                assert rec == "review", f"Expected 'review' for score {p['score']} in [{review_th}, {keep_th}), got {rec}"

        print(f"  ✓ {p['filename']:15s} -> score={p['score']:.1f}, recommendation='{rec}', status='{stat}'")
    print("  --> PASS: recommendation and status match configured thresholds (keep/review/reject).")

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 3:
    # "reasons is a non-empty, sensible list for every photo"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 3] Reasons is non-empty, sensible list for every photo...")
    for pid, p in photos.items():
        raw_reasons = p["reasons"]
        assert raw_reasons is not None, f"Photo {pid} has null reasons"
        reasons = json.loads(raw_reasons) if isinstance(raw_reasons, str) else raw_reasons
        assert isinstance(reasons, list), f"Photo {pid} reasons is not a list: {type(reasons)}"
        assert len(reasons) > 0, f"Photo {pid} reasons list is empty"
        for r in reasons:
            assert isinstance(r, str) and len(r.strip()) > 0, f"Empty or non-string reason in {pid}: {r}"
        print(f"  ✓ {p['filename']:15s} -> {len(reasons)} reasons: {reasons}")
    print("  --> PASS: Every photo has a non-empty, sensible list of reasons.")


    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 4:
    # "Non-representative members of a similarity cluster are never status='keep' even with a high raw score"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 4] Non-representative cluster members are never status='keep'...")
    # Test explicitly with a high raw score (e.g. 95)
    rec_high_dup, reasons_high_dup = generate_recommendation(
        score=95.0,
        duplicate=True,
        is_ai_pick=False,
        details={"norm_sharpness": 95.0, "norm_exposure": 95.0, "composition_score": 95.0},
    )
    assert rec_high_dup != "keep", f"Duplicate non-pick received '{rec_high_dup}' despite raw score 95!"
    assert rec_high_dup == "review", f"Expected 'review', got {rec_high_dup}"
    assert "Duplicate frame in similarity cluster" in reasons_high_dup

    # Check database photos for cluster non-pick
    c1 = photos_by_name["cluster_1.jpg"]
    c2 = photos_by_name["cluster_2.jpg"]
    non_pick = c1 if c1["duplicate"] else c2
    assert non_pick["status"] != "keep", f"Non-pick member has status='keep': {non_pick}"
    assert non_pick["recommendation"] != "keep"
    print(f"  ✓ High-scoring duplicate (score=95) forced to recommendation='{rec_high_dup}'")
    print(f"  ✓ DB non-pick {non_pick['filename']} status='{non_pick['status']}', duplicate={non_pick['duplicate']}")
    print("  --> PASS: Non-representative cluster members are strictly prevented from status='keep'.")

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 5:
    # "Changing a weight in config/scoring_weights.json and re-running scoring changes results without touching code"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 5] Changing config/scoring_weights.json changes scoring without code edits...")
    orig_weights_text = _WEIGHTS_PATH.read_text(encoding="utf-8")
    try:
        score_before = photos_by_name["portrait.jpg"]["score"]

        # Modify weight on disk
        weights_dict = json.loads(orig_weights_text)
        weights_dict["sharpness"] = 0.80  # Drastically increase sharpness weight
        weights_dict["composition"] = 0.05
        _WEIGHTS_PATH.write_text(json.dumps(weights_dict, indent=2), encoding="utf-8")

        # Re-run scoring without restarting or touching code
        rescore_batch(batch_id)

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        updated_portrait = conn.execute("SELECT score FROM photos WHERE batch_id = ? AND filename = 'portrait.jpg'", (batch_id,)).fetchone()
        conn.close()
        score_after = updated_portrait["score"]

        assert score_before != score_after, f"Score did not change! Before: {score_before}, After: {score_after}"
        print(f"  ✓ Score before weight change: {score_before:.2f}")
        print(f"  ✓ Score after weight change:  {score_after:.2f} (diff = {score_after - score_before:+.2f})")
    finally:
        # Restore original weights
        _WEIGHTS_PATH.write_text(orig_weights_text, encoding="utf-8")
        rescore_batch(batch_id)
        print("  ✓ Restored original weights on disk.")
    print("  --> PASS: Modifying scoring_weights.json dynamically modifies scores on re-scoring.")

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 6:
    # "Phase 4's AI Pick per cluster is re-selected using final score (highest score wins, not just sharpness)"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 6] AI Pick re-selected using final composite score (highest score wins)...")
    # cluster_1 had sharpness 280 (high), but poor exposure/composition.
    # cluster_2 had sharpness 190 (lower), but optimal exposure/composition.
    # Check that cluster_2 won the AI Pick despite having lower sharpness!
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    p1 = conn.execute("SELECT * FROM photos WHERE batch_id = ? AND filename = 'cluster_1.jpg'", (batch_id,)).fetchone()
    p2 = conn.execute("SELECT * FROM photos WHERE batch_id = ? AND filename = 'cluster_2.jpg'", (batch_id,)).fetchone()
    conn.close()

    print(f"  Photo 1 (sharp={p1['sharpness_score']}): score={p1['score']:.1f}, duplicate={p1['duplicate']}, status='{p1['status']}'")
    print(f"  Photo 2 (sharp={p2['sharpness_score']}): score={p2['score']:.1f}, duplicate={p2['duplicate']}, status='{p2['status']}'")

    assert p1["sharpness_score"] > p2["sharpness_score"], "Prerequisite: Photo 1 must have higher sharpness"
    # Highest final score must be designated AI Pick (duplicate=0)
    if p2["score"] > p1["score"]:
        assert p2["duplicate"] == 0, "Photo 2 has higher composite score and must be AI Pick (duplicate=0)"
        assert p1["duplicate"] == 1, "Photo 1 must be marked duplicate=1"
        assert p2["status"] == "keep"
        print(f"  ✓ Winner is {p2['filename']} (composite score {p2['score']:.1f} > {p1['score']:.1f}) despite lower sharpness!")
    else:
        assert p1["duplicate"] == 0
        assert p2["duplicate"] == 1
        print(f"  ✓ Winner is {p1['filename']} (composite score {p1['score']:.1f} > {p2['score']:.1f})")
    print("  --> PASS: AI Pick is selected using final composite score, not raw sharpness.")

    # ──────────────────────────────────────────────────────────────────────────
    # CRITERION 7:
    # "Photos with zero faces still get a sensible score (not null, not zero by default)"
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[CRITERION 7] Photos with zero faces get a sensible score (not null, not zero)...")
    landscape = photos_by_name["landscape.jpg"]
    assert landscape["face_count"] == 0, f"Expected face_count 0, got {landscape['face_count']}"
    assert landscape["face_score"] is not None and landscape["face_score"] > 0, f"face_score={landscape['face_score']}"
    assert landscape["face_score"] == 60.0, f"Neutral face score should be 60.0, got {landscape['face_score']}"
    assert landscape["score"] is not None and landscape["score"] >= 65.0, f"Final score is {landscape['score']}"
    assert landscape["recommendation"] in ("keep", "review")
    print(f"  ✓ Zero-face landscape: face_count={landscape['face_count']}, face_score={landscape['face_score']}, comp_score={landscape['composition_score']:.1f}, final_score={landscape['score']:.1f}, recommendation='{landscape['recommendation']}'")
    print("  --> PASS: Zero-face photo received sensible score (~75-80), not null or zero.")


    print("\n" + "=" * 70)
    print("ALL 7 ACCEPTANCE CRITERIA VERIFIED AND PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_all_checks()
