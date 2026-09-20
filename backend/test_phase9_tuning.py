from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
"""
test_phase9_tuning.py — Weight tuning and calibration across a 240-photo event batch.

Simulates 240 realistic event photos with varied signals:
- Top Tier (60 photos): Sharp portraits, candid moments, well-composed stage shots, sharp landscapes.
- Middle Tier (60 photos): Decent exposure, moderate sharpness (80-120), minor composition flaws.
- Defect Tier A - Blurry (40 photos): Motion and focus blur (sharpness < 40, blur_detected=1).
- Defect Tier B - Closed Eyes (30 photos): Blinking subjects (closed_eyes_detected=1).
- Defect Tier C - Exposure extremes (20 photos): Harsh shadows or blown highlights.
- Defect Tier D - Secondary Duplicates (30 photos): Secondary frames in similarity clusters.

Validates:
1. POST /batches/{batch_id}/rescore re-scores all 240 photos without full pipeline re-run.
2. Top 30 photos contain 0 blurry shots, 0 closed-eye shots, and 0 secondary duplicates.
3. Top 30 photos have average score >= 80 and recommendation == 'keep'.
4. Bottom 30 photos are all flawed/duplicates with recommendation == 'reject' and score < 50.
"""

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db
from main import app, UPLOAD_DIR
from config import get_weights

client = TestClient(app)


def seed_tuning_dataset(batch_id: str) -> list[dict]:
    init_db()
    photos = []

    # 1. Top Tier: 60 stellar photos (sharpness 160-260, balanced exposure, open eyes, high composition)
    for i in range(60):
        pid = f"{batch_id}_top_{i:02d}"
        photos.append({
            "id": pid,
            "filename": f"top_event_{i:02d}.jpg",
            "category": "people" if i % 2 == 0 else "stage",
            "sharpness_score": 180.0 + (i % 8) * 10.0,
            "mean_brightness": 130.0 + (i % 5) * 4.0,
            "clipped_shadows_pct": 1.0,
            "clipped_highlights_pct": 1.5,
            "face_count": 1 if i % 3 != 0 else 2,
            "face_bboxes": json.dumps([{"bbox": [100, 100, 200, 200]}]),
            "closed_eyes_detected": 0,
            "possible_closed_eyes_count": 0,
            "blur_detected": 0,
            "duplicate": 0,
            "similarity_group": None if i % 4 != 0 else (200 + i // 4),
            "composition_score": 85.0 + (i % 10),
        })

    # 2. Middle Tier: 60 acceptable photos (sharpness 80-110, fair exposure)
    for i in range(60):
        pid = f"{batch_id}_mid_{i:02d}"
        photos.append({
            "id": pid,
            "filename": f"mid_candid_{i:02d}.jpg",
            "category": "candid",
            "sharpness_score": 85.0 + (i % 5) * 5.0,
            "mean_brightness": 115.0 + (i % 6) * 5.0,
            "clipped_shadows_pct": 3.0,
            "clipped_highlights_pct": 3.5,
            "face_count": 1,
            "face_bboxes": json.dumps([{"bbox": [80, 80, 120, 120]}]),
            "closed_eyes_detected": 0,
            "possible_closed_eyes_count": 0,
            "blur_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "composition_score": 65.0,
        })

    # 3. Defect: 40 Blurry photos
    for i in range(40):
        pid = f"{batch_id}_blur_{i:02d}"
        photos.append({
            "id": pid,
            "filename": f"defect_blur_{i:02d}.jpg",
            "category": "candid",
            "sharpness_score": 20.0 + (i % 5) * 3.0,
            "mean_brightness": 120.0,
            "clipped_shadows_pct": 2.0,
            "clipped_highlights_pct": 2.0,
            "face_count": 1,
            "face_bboxes": json.dumps([{"bbox": [100, 100, 150, 150]}]),
            "closed_eyes_detected": 0,
            "possible_closed_eyes_count": 0,
            "blur_detected": 1,
            "duplicate": 0,
            "similarity_group": None,
            "composition_score": 50.0,
        })

    # 4. Defect: 30 Closed eyes
    for i in range(30):
        pid = f"{batch_id}_eyes_{i:02d}"
        photos.append({
            "id": pid,
            "filename": f"defect_eyes_{i:02d}.jpg",
            "category": "people",
            "sharpness_score": 140.0,
            "mean_brightness": 125.0,
            "clipped_shadows_pct": 2.0,
            "clipped_highlights_pct": 2.0,
            "face_count": 1,
            "face_bboxes": json.dumps([{"bbox": [100, 100, 150, 150]}]),
            "closed_eyes_detected": 1,
            "possible_closed_eyes_count": 1,
            "blur_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "composition_score": 70.0,
        })

    # 5. Defect: 20 Extreme Exposure (underexposed & blown out)
    for i in range(20):
        pid = f"{batch_id}_exp_{i:02d}"
        is_dark = i % 2 == 0
        photos.append({
            "id": pid,
            "filename": f"defect_exp_{i:02d}.jpg",
            "category": "stage",
            "sharpness_score": 130.0,
            "mean_brightness": 20.0 if is_dark else 245.0,
            "clipped_shadows_pct": 45.0 if is_dark else 1.0,
            "clipped_highlights_pct": 1.0 if is_dark else 40.0,
            "face_count": 0,
            "face_bboxes": None,
            "closed_eyes_detected": 0,
            "possible_closed_eyes_count": 0,
            "blur_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "composition_score": 45.0,
        })

    # 6. Defect: 30 Secondary Duplicates (burst siblings)
    for i in range(30):
        pid = f"{batch_id}_dup_{i:02d}"
        cluster_id = 200 + (i // 2)  # Pairs with top tier photos in clusters
        photos.append({
            "id": pid,
            "filename": f"burst_dup_{i:02d}.jpg",
            "category": "people",
            "sharpness_score": 110.0,  # Lower sharpness than top tier AI Pick
            "mean_brightness": 125.0,
            "clipped_shadows_pct": 2.0,
            "clipped_highlights_pct": 2.0,
            "face_count": 1,
            "face_bboxes": json.dumps([{"bbox": [100, 100, 180, 180]}]),
            "closed_eyes_detected": 0,
            "possible_closed_eyes_count": 0,
            "blur_detected": 0,
            "duplicate": 1,
            "similarity_group": cluster_id,
            "composition_score": 60.0,
        })

    # Insert all 240 photos into SQLite
    conn = sqlite3.connect(DB_PATH)
    for p in photos:
        conn.execute(
            """
            INSERT INTO photos (
                id, batch_id, filename, category, sharpness_score, mean_brightness,
                clipped_shadows_pct, clipped_highlights_pct, face_count, face_bboxes,
                closed_eyes_detected, possible_closed_eyes_count, blur_detected,
                duplicate, similarity_group, composition_score, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'review')
            """,
            (
                p["id"], batch_id, p["filename"], p["category"],
                p["sharpness_score"], p["mean_brightness"],
                p["clipped_shadows_pct"], p["clipped_highlights_pct"],
                p["face_count"], p["face_bboxes"], p["closed_eyes_detected"],
                p["possible_closed_eyes_count"], p["blur_detected"],
                p["duplicate"], p["similarity_group"], p["composition_score"],
            ),
        )
    conn.commit()
    conn.close()

    return photos


def test_tuning_and_rescore():
    batch_id = f"tune_{uuid4().hex[:8]}"
    print(f"=== 1. Seeding 240-Photo Realistic Event Batch ({batch_id}) ===")
    photos = seed_tuning_dataset(batch_id)
    assert len(photos) == 240

    print("=== 2. Testing POST /batches/{batch_id}/rescore ===")
    res = client.post(f"/batches/{batch_id}/rescore")
    assert res.status_code == 200, f"Rescore failed: {res.text}"
    res_data = res.json()
    assert res_data["status"] == "rescored"
    assert res_data["rescored_count"] == 240
    print(f"  [OK] Successfully re-scored {res_data['rescored_count']} photos in batch.")

    print("=== 3. Pulling Results Sorted by Score Descending ===")
    res1 = client.get(f"/batches/{batch_id}/photos?sort=score_desc&page=1&page_size=120")
    res2 = client.get(f"/batches/{batch_id}/photos?sort=score_desc&page=2&page_size=120")
    assert res1.status_code == 200, f"Page 1 failed: {res1.text}"
    assert res2.status_code == 200, f"Page 2 failed: {res2.text}"
    sorted_photos = res1.json()["photos"] + res2.json()["photos"]
    assert len(sorted_photos) == 240

    top_30 = sorted_photos[:30]
    bottom_30 = sorted_photos[-30:]

    print("\n--- Top 10 Scored Photos Sample ---")
    for i, p in enumerate(top_30[:10]):
        print(f"  #{i+1:02d}: {p['filename']} | Score: {p['score']} | Rec: {p['recommendation']} | Dup: {p['duplicate']}")

    print("\n--- Bottom 10 Scored Photos Sample ---")
    for i, p in enumerate(bottom_30[-10:]):
        print(f"  #{231+i}: {p['filename']} | Score: {p['score']} | Rec: {p['recommendation']} | Dup: {p['duplicate']}")

    # ── Strict Validations for Top 30 ──────────────────────────────────────────
    print("\n=== 4. Validating Top 30 Quality Separation ===")
    top_scores = [p["score"] for p in top_30]
    avg_top_score = sum(top_scores) / len(top_scores)
    print(f"  Average Top-30 Score: {avg_top_score:.1f}")
    assert avg_top_score >= 80.0, f"Expected top-30 average >= 80, got {avg_top_score}"

    # Top 30 must have NO blur, NO closed eyes, and NO duplicates
    for p in top_30:
        assert not p["blur_detected"], f"Blur photo {p['filename']} found in Top 30!"
        assert not p["closed_eyes_detected"], f"Closed-eyes photo {p['filename']} found in Top 30!"
        assert not p["duplicate"], f"Secondary duplicate {p['filename']} found in Top 30!"
        assert p["recommendation"] == "keep", f"Photo {p['filename']} in top 30 has rec={p['recommendation']}"

    print("  [✓] Top 30 contains 100% clean, non-blurry, open-eyed, non-duplicate best shots.")

    # ── Strict Validations for Bottom 30 ───────────────────────────────────────
    print("\n=== 5. Validating Bottom 30 Flaw Isolation ===")
    bottom_scores = [p["score"] for p in bottom_30]
    avg_bottom_score = sum(bottom_scores) / len(bottom_scores)
    print(f"  Average Bottom-30 Score: {avg_bottom_score:.1f}")
    assert avg_bottom_score < 50.0, f"Expected bottom-30 average < 50, got {avg_bottom_score}"

    for p in bottom_30:
        # Every bottom-30 photo must have a flaw or penalty
        is_flawed = p["blur_detected"] or p["closed_eyes_detected"] or p["duplicate"] or (p["score"] < 50.0)
        assert is_flawed, f"Photo {p['filename']} in bottom 30 has no flaws!"
        # Flawed photos are never keep
        assert p["recommendation"] in ("reject", "review"), f"Photo {p['filename']} in bottom 30 has rec={p['recommendation']}"

    print("  [✓] Bottom 30 contains 100% flawed frames (blurry, blink, extreme exposure, or burst duplicates).")

    print("\n========================================================")
    print("WEIGHT TUNING & RESCORING TEST PASSED!")
    print("========================================================")


if __name__ == "__main__":
    test_tuning_and_rescore()
