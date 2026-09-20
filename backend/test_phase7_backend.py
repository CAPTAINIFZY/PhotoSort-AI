from __future__ import annotations

import io
import os
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
"""
test_phase7_backend.py — Unit & Integration tests for Phase 7 backend endpoints.
"""

import os
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db
from main import app, UPLOAD_DIR, THUMBNAIL_DIR

client = TestClient(app)


def setup_phase7_data() -> tuple[str, list[dict]]:
    init_db()
    batch_id = f"test_p7_{uuid4().hex[:8]}"

    photos_data = [
        # 1. Best shot, people, cluster 201 (AI Pick)
        {
            "id": f"{batch_id}_p1",
            "filename": "person_best.jpg",
            "category": "people",
            "score": 95.0,
            "sharpness_score": 92.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": 201,
            "recommendation": "keep",
            "status": "keep",
            "created_at": "2026-09-20T10:00:00",
        },
        # 2. Duplicate of Photo 1, cluster 201
        {
            "id": f"{batch_id}_p2",
            "filename": "person_dup.jpg",
            "category": "people",
            "score": 75.0,
            "sharpness_score": 80.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 1,
            "similarity_group": 201,
            "recommendation": "review",
            "status": "review",
            "created_at": "2026-09-20T10:00:05",
        },
        # 3. Stage, sharp, keep, singleton
        {
            "id": f"{batch_id}_p3",
            "filename": "stage_act.jpg",
            "category": "stage",
            "score": 88.0,
            "sharpness_score": 90.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "recommendation": "keep",
            "status": "keep",
            "created_at": "2026-09-20T10:01:00",
        },
        # 4. Candid, closed eyes, review, singleton
        {
            "id": f"{batch_id}_p4",
            "filename": "candid_blink.jpg",
            "category": "candid",
            "score": 55.0,
            "sharpness_score": 70.0,
            "blur_detected": 0,
            "closed_eyes_detected": 1,
            "duplicate": 0,
            "similarity_group": None,
            "recommendation": "review",
            "status": "review",
            "created_at": "2026-09-20T10:02:00",
        },
        # 5. Group, blur, reject, singleton
        {
            "id": f"{batch_id}_p5",
            "filename": "group_blur.jpg",
            "category": "group",
            "score": 35.0,
            "sharpness_score": 30.0,
            "blur_detected": 1,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "recommendation": "reject",
            "status": "reject",
            "created_at": "2026-09-20T10:03:00",
        },
    ]

    conn = sqlite3.connect(DB_PATH)
    for p in photos_data:
        conn.execute(
            """
            INSERT INTO photos (
                id, batch_id, filename, category, score, sharpness_score,
                blur_detected, closed_eyes_detected, duplicate,
                similarity_group, recommendation, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"],
                batch_id,
                p["filename"],
                p["category"],
                p["score"],
                p["sharpness_score"],
                p["blur_detected"],
                p["closed_eyes_detected"],
                p["duplicate"],
                p["similarity_group"],
                p["recommendation"],
                p["status"],
                p["created_at"],
            ),
        )
    conn.commit()
    conn.close()

    # Create dummy original and thumbnail for photo 1
    orig_dir = Path(UPLOAD_DIR) / batch_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    (orig_dir / f"{photos_data[0]['id']}.jpg").write_bytes(b"\xff\xd8\xff\xe0testimageoriginal")

    thumb_dir = Path(THUMBNAIL_DIR) / batch_id
    thumb_dir.mkdir(parents=True, exist_ok=True)
    (thumb_dir / f"{photos_data[0]['id']}.jpg").write_bytes(b"\xff\xd8\xff\xe0testimagethumb")

    return batch_id, photos_data


def test_photo_detail_extension():
    batch_id, photos = setup_phase7_data()

    # 1. Clustered photo (Photo 1)
    res = client.get(f"/photos/{photos[0]['id']}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert data["id"] == photos[0]["id"]
    assert data["thumbnail_url"] == f"/thumbnails/{batch_id}/{photos[0]['id']}.jpg"
    assert "/originals/" in data["original_url"] or "/photos/" in data["original_url"]
    assert data["cluster"] is not None
    cluster = data["cluster"]
    assert cluster["similarity_group"] == 201
    assert cluster["ai_pick_id"] == photos[0]["id"]
    assert len(cluster["members"]) == 2
    # Verify exactly one member is marked is_ai_pick
    ai_picks = [m for m in cluster["members"] if m["is_ai_pick"]]
    assert len(ai_picks) == 1
    assert ai_picks[0]["id"] == photos[0]["id"]

    # 2. Singleton photo (Photo 3)
    res_single = client.get(f"/photos/{photos[2]['id']}")
    assert res_single.status_code == 200
    data_single = res_single.json()
    assert data_single["cluster"] is None
    print("  [OK] test_photo_detail_extension passed")


def test_adjacent_photos():
    batch_id, photos = setup_phase7_data()

    # In default sort (score_desc):
    # Order: Photo 1 (95.0), Photo 3 (88.0), Photo 2 (75.0), Photo 4 (55.0), Photo 5 (35.0)
    p1, p2, p3, p4, p5 = photos[0]["id"], photos[1]["id"], photos[2]["id"], photos[3]["id"], photos[4]["id"]

    # Middle photo (Photo 3, score 88.0)
    res = client.get(f"/photos/{p3}/adjacent?batch_id={batch_id}&sort=score_desc")
    assert res.status_code == 200
    adj = res.json()
    assert adj["prev_id"] == p1, f"Expected prev={p1}, got {adj['prev_id']}"
    assert adj["next_id"] == p2, f"Expected next={p2}, got {adj['next_id']}"

    # First photo (Photo 1, score 95.0)
    res_first = client.get(f"/photos/{p1}/adjacent?batch_id={batch_id}&sort=score_desc")
    assert res_first.status_code == 200
    adj_first = res_first.json()
    assert adj_first["prev_id"] is None
    assert adj_first["next_id"] == p3

    # Last photo (Photo 5, score 35.0)
    res_last = client.get(f"/photos/{p5}/adjacent?batch_id={batch_id}&sort=score_desc")
    assert res_last.status_code == 200
    adj_last = res_last.json()
    assert adj_last["prev_id"] == p4
    assert adj_last["next_id"] is None

    # Filtered context (filter=best_shots)
    # Matching: p1 (keep) and p3 (keep)
    res_best_p1 = client.get(f"/photos/{p1}/adjacent?batch_id={batch_id}&filter=best_shots&sort=score_desc")
    assert res_best_p1.status_code == 200
    adj_best_p1 = res_best_p1.json()
    assert adj_best_p1["prev_id"] is None
    assert adj_best_p1["next_id"] == p3

    # Single item filter (filter=closed_eyes -> only p4)
    res_eyes = client.get(f"/photos/{p4}/adjacent?batch_id={batch_id}&filter=closed_eyes")
    assert res_eyes.status_code == 200
    adj_eyes = res_eyes.json()
    assert adj_eyes["prev_id"] is None
    assert adj_eyes["next_id"] is None

    # Photo not in filter (p1 requested with filter=closed_eyes)
    res_filtered_out = client.get(f"/photos/{p1}/adjacent?batch_id={batch_id}&filter=closed_eyes")
    assert res_filtered_out.status_code == 200
    assert res_filtered_out.json()["prev_id"] is None
    assert res_filtered_out.json()["next_id"] is None
    print("  [OK] test_adjacent_photos passed")


def test_original_image_serving():
    batch_id, photos = setup_phase7_data()

    # 1. GET /photos/{photo_id}/original
    res = client.get(f"/photos/{photos[0]['id']}/original")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content == b"\xff\xd8\xff\xe0testimageoriginal"

    # 2. Static /originals/{batch_id}/{filename}
    res_static = client.get(f"/originals/{batch_id}/{photos[0]['id']}.jpg")
    assert res_static.status_code == 200
    assert res_static.content == b"\xff\xd8\xff\xe0testimageoriginal"

    # 3. 404 on missing original file
    res_missing = client.get(f"/photos/{photos[1]['id']}/original")
    assert res_missing.status_code == 404

    # 4. 404 on non-existent photo ID
    res_nonexistent = client.get("/photos/non_existent_id/original")
    assert res_nonexistent.status_code == 404
    print("  [OK] test_original_image_serving passed")


if __name__ == "__main__":
    print("Running Phase 7 Backend Tests...")
    test_photo_detail_extension()
    test_adjacent_photos()
    test_original_image_serving()
    print("\nALL PHASE 7 BACKEND TESTS PASSED!")
