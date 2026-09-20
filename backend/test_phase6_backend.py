"""
test_phase6_backend.py — Unit & Integration tests for Phase 6 backend endpoints.

Tests:
1. GET /batches/{batch_id}/summary returns correct aggregate counts and categories.
2. GET /batches/{batch_id}/photos applies filters correctly in SQL.
3. GET /batches/{batch_id}/photos applies sort orders correctly (including similarity nulls-last).
4. GET /batches/{batch_id}/photos pagination works (page, page_size, total).
5. Static thumbnail serving via /thumbnails/... and GET /photos/{id}/thumbnail.
6. 404 responses for non-existent batches and photos.
"""

from __future__ import annotations

import json
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
from main import app, THUMBNAIL_DIR

client = TestClient(app)


def setup_test_data() -> tuple[str, list[dict]]:
    init_db()
    batch_id = f"test_p6_{uuid4().hex[:8]}"

    photos_data = [
        # 1. Best shot, people category, high score
        {
            "id": f"{batch_id}_p1",
            "filename": "person_best.jpg",
            "category": "people",
            "score": 92.5,
            "sharpness_score": 250.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": 10,
            "recommendation": "keep",
            "status": "keep",
            "created_at": "2026-09-20T10:00:00",
        },
        # 2. Stage photo, moderate score, review
        {
            "id": f"{batch_id}_p2",
            "filename": "stage_act.jpg",
            "category": "stage",
            "score": 68.0,
            "sharpness_score": 180.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,  # Singleton
            "recommendation": "review",
            "status": "review",
            "created_at": "2026-09-20T10:01:00",
        },
        # 3. Duplicate photo, candid, review
        {
            "id": f"{batch_id}_p3",
            "filename": "candid_dup.jpg",
            "category": "candid",
            "score": 58.0,
            "sharpness_score": 190.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 1,
            "similarity_group": 10,  # Same cluster as p1
            "recommendation": "review",
            "status": "review",
            "created_at": "2026-09-20T10:02:00",
        },
        # 4. Blurry photo, group, reject
        {
            "id": f"{batch_id}_p4",
            "filename": "group_blur.jpg",
            "category": "group",
            "score": 38.0,
            "sharpness_score": 25.0,
            "blur_detected": 1,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,  # Singleton
            "recommendation": "reject",
            "status": "reject",
            "created_at": "2026-09-20T10:03:00",
        },
        # 5. Closed eyes photo, people, low score
        {
            "id": f"{batch_id}_p5",
            "filename": "eyes_closed.jpg",
            "category": "people",
            "score": 42.0,
            "sharpness_score": 160.0,
            "blur_detected": 0,
            "closed_eyes_detected": 1,
            "duplicate": 0,
            "similarity_group": 20,
            "recommendation": "reject",
            "status": "reject",
            "created_at": "2026-09-20T10:04:00",
        },
        # 6. Other category, singleton, moderate score
        {
            "id": f"{batch_id}_p6",
            "filename": "decor_item.jpg",
            "category": "other",
            "score": 76.0,
            "sharpness_score": 210.0,
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "recommendation": "keep",
            "status": "keep",
            "created_at": "2026-09-20T10:05:00",
        },
    ]

    # Create dummy thumbnail files
    thumb_dir = Path(THUMBNAIL_DIR) / batch_id
    thumb_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    for p in photos_data:
        # Create thumbnail file
        t_file = thumb_dir / f"{p['id']}.jpg"
        t_file.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIFdummy")

        conn.execute(
            """
            INSERT INTO photos (
                id, filename, batch_id, category, score, sharpness_score,
                blur_detected, closed_eyes_detected, duplicate,
                similarity_group, recommendation, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"], p["filename"], batch_id, p["category"], p["score"],
                p["sharpness_score"], p["blur_detected"], p["closed_eyes_detected"],
                p["duplicate"], p["similarity_group"], p["recommendation"],
                p["status"], p["created_at"],
            ),
        )
    conn.commit()
    conn.close()

    return batch_id, photos_data


def test_batch_summary():
    batch_id, photos = setup_test_data()

    res = client.get(f"/batches/{batch_id}/summary")
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["total"] == 6
    assert data["best_shots"] == 2  # p1, p6
    assert data["blur_count"] == 1  # p4
    assert data["duplicate_count"] == 1  # p3
    assert data["closed_eyes_count"] == 1  # p5
    assert data["low_score_count"] == 2  # p4 (38), p5 (42) < 50

    cats = data["categories"]
    assert cats["people"] == 2  # p1, p5
    assert cats["stage"] == 1   # p2
    assert cats["candid"] == 1  # p3
    assert cats["group"] == 1   # p4
    assert cats["other"] == 1   # p6


def test_batch_photos_filters():
    batch_id, photos = setup_test_data()

    # Filter: best_shots
    r = client.get(f"/batches/{batch_id}/photos?filter=best_shots")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert all(p["recommendation"] == "keep" for p in d["photos"])

    # Filter: blur
    r = client.get(f"/batches/{batch_id}/photos?filter=blur")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 1
    assert d["photos"][0]["filename"] == "group_blur.jpg"
    assert d["photos"][0]["blur_detected"] is True

    # Filter: duplicates
    r = client.get(f"/batches/{batch_id}/photos?filter=duplicates")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 1
    assert d["photos"][0]["filename"] == "candid_dup.jpg"
    assert d["photos"][0]["duplicate"] is True

    # Filter: closed_eyes
    r = client.get(f"/batches/{batch_id}/photos?filter=closed_eyes")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 1
    assert d["photos"][0]["filename"] == "eyes_closed.jpg"
    assert d["photos"][0]["closed_eyes_detected"] is True

    # Filter: low_score
    r = client.get(f"/batches/{batch_id}/photos?filter=low_score")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert all(p["score"] < 50.0 for p in d["photos"])

    # Filter: category=people
    r = client.get(f"/batches/{batch_id}/photos?category=people")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert all(p["category"] == "people" for p in d["photos"])

    # Filter: status=reject
    r = client.get(f"/batches/{batch_id}/photos?status=reject")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    assert all(p["status"] == "reject" for p in d["photos"])


def test_batch_photos_sorting():
    batch_id, photos = setup_test_data()

    # Sort: score_desc (default)
    r = client.get(f"/batches/{batch_id}/photos?sort=score_desc")
    assert r.status_code == 200
    scores = [p["score"] for p in r.json()["photos"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 92.5

    # Sort: newest
    r = client.get(f"/batches/{batch_id}/photos?sort=newest")
    assert r.status_code == 200
    assert r.json()["photos"][0]["filename"] == "decor_item.jpg"

    # Sort: oldest
    r = client.get(f"/batches/{batch_id}/photos?sort=oldest")
    assert r.status_code == 200
    assert r.json()["photos"][0]["filename"] == "person_best.jpg"

    # Sort: sharpness_desc
    r = client.get(f"/batches/{batch_id}/photos?sort=sharpness_desc")
    assert r.status_code == 200
    assert r.json()["photos"][0]["filename"] == "person_best.jpg"

    # Sort: similarity (grouped clusters first in order, NULLs last)
    r = client.get(f"/batches/{batch_id}/photos?sort=similarity")
    assert r.status_code == 200
    p_list = r.json()["photos"]
    sim_groups = [p["similarity_group"] for p in p_list]
    # Cluster 10 (2 items), Cluster 20 (1 item), then None (3 items)
    assert sim_groups[:2] == [10, 10]
    assert sim_groups[2] == 20
    assert sim_groups[3:] == [None, None, None]


def test_batch_photos_pagination():
    batch_id, photos = setup_test_data()

    # Page 1 (page_size = 2)
    r1 = client.get(f"/batches/{batch_id}/photos?page=1&page_size=2&sort=score_desc")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["total"] == 6
    assert d1["page"] == 1
    assert d1["page_size"] == 2
    assert len(d1["photos"]) == 2
    assert d1["photos"][0]["score"] == 92.5
    assert d1["photos"][1]["score"] == 76.0

    # Page 2
    r2 = client.get(f"/batches/{batch_id}/photos?page=2&page_size=2&sort=score_desc")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["page"] == 2
    assert len(d2["photos"]) == 2
    assert d2["photos"][0]["score"] == 68.0
    assert d2["photos"][1]["score"] == 58.0


def test_thumbnail_serving():
    batch_id, photos = setup_test_data()
    photo_id = photos[0]["id"]

    # 1. Static route /thumbnails/{batch_id}/{photo_id}.jpg
    r_static = client.get(f"/thumbnails/{batch_id}/{photo_id}.jpg")
    assert r_static.status_code == 200
    assert r_static.headers["content-type"] in ("image/jpeg", "image/jpg")

    # 2. Endpoint GET /photos/{photo_id}/thumbnail
    r_api = client.get(f"/photos/{photo_id}/thumbnail")
    assert r_api.status_code == 200
    assert r_api.headers["content-type"] == "image/jpeg"


def test_404_responses():
    r_sum = client.get("/batches/non_existent_batch_xyz/summary")
    assert r_sum.status_code == 404

    r_photos = client.get("/batches/non_existent_batch_xyz/photos")
    assert r_photos.status_code == 404

    r_thumb = client.get("/photos/non_existent_photo_xyz/thumbnail")
    assert r_thumb.status_code == 404


if __name__ == "__main__":
    print("Running Phase 6 Backend Tests...")
    test_batch_summary()
    print("  [PASS] test_batch_summary")
    test_batch_photos_filters()
    print("  [PASS] test_batch_photos_filters")
    test_batch_photos_sorting()
    print("  [PASS] test_batch_photos_sorting")
    test_batch_photos_pagination()
    print("  [PASS] test_batch_photos_pagination")
    test_thumbnail_serving()
    print("  [PASS] test_thumbnail_serving")
    test_404_responses()
    print("  [PASS] test_404_responses")
    print("\nALL PHASE 6 BACKEND TESTS PASSED!")
