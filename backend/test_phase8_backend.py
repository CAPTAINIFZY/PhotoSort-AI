from __future__ import annotations

import io
import os
import sqlite3
import sys
import zipfile
import csv
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
"""
test_phase8_backend.py — Unit & Integration tests for Phase 8 backend endpoints.

Tests:
1. PATCH /photos/{photo_id}/status updates status, preserves recommendation, validates inputs.
2. PATCH /batches/{batch_id}/photos/status updates multiple photos atomically.
3. POST /batches/{batch_id}/export streams valid ZIP of selected photos with collision safety and missing-file resilience.
4. GET /batches/{batch_id}/export/report returns valid CSV matching database figures.
"""

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db
from main import app, UPLOAD_DIR, THUMBNAIL_DIR

client = TestClient(app)


def setup_phase8_test_data() -> tuple[str, list[dict]]:
    init_db()
    batch_id = f"test_p8_{uuid4().hex[:8]}"

    photos_data = [
        {
            "id": f"{batch_id}_p1",
            "filename": "img_same_name.jpg",
            "category": "people",
            "score": 92.0,
            "recommendation": "keep",
            "status": "keep",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "created_at": "2026-09-20T12:00:00",
        },
        {
            "id": f"{batch_id}_p2",
            "filename": "img_same_name.jpg",  # Collision test
            "category": "people",
            "score": 75.0,
            "recommendation": "review",
            "status": "review",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 1,
            "similarity_group": None,
            "created_at": "2026-09-20T12:00:05",
        },
        {
            "id": f"{batch_id}_p3",
            "filename": "stage_show.jpg",
            "category": "stage",
            "score": 88.0,
            "recommendation": "keep",
            "status": "keep",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "created_at": "2026-09-20T12:01:00",
        },
        {
            "id": f"{batch_id}_p4",
            "filename": "blur_action.jpg",
            "category": "candid",
            "score": 40.0,
            "recommendation": "reject",
            "status": "reject",
            "blur_detected": 1,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "created_at": "2026-09-20T12:02:00",
        },
    ]

    conn = sqlite3.connect(DB_PATH)
    for p in photos_data:
        conn.execute(
            """
            INSERT INTO photos (
                id, batch_id, filename, category, score, recommendation, status,
                blur_detected, closed_eyes_detected, duplicate, similarity_group, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"],
                batch_id,
                p["filename"],
                p["category"],
                p["score"],
                p["recommendation"],
                p["status"],
                p["blur_detected"],
                p["closed_eyes_detected"],
                p["duplicate"],
                p["similarity_group"],
                p["created_at"],
            ),
        )
    conn.commit()
    conn.close()

    # Create dummy original files on disk for p1, p2, p3
    orig_dir = Path(UPLOAD_DIR) / batch_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    (orig_dir / f"{photos_data[0]['id']}.jpg").write_bytes(b"\xff\xd8\xff\xe0data_for_p1")
    (orig_dir / f"{photos_data[1]['id']}.jpg").write_bytes(b"\xff\xd8\xff\xe0data_for_p2")
    (orig_dir / f"{photos_data[2]['id']}.jpg").write_bytes(b"\xff\xd8\xff\xe0data_for_p3")
    # Leave p4 uncreated on disk to test missing-file resilience

    return batch_id, photos_data


def test_single_photo_status_update():
    batch_id, photos = setup_phase8_test_data()
    p2 = photos[1]

    # Change p2 from review -> keep
    res = client.patch(f"/photos/{p2['id']}/status", json={"status": "keep"})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["id"] == p2["id"]
    assert data["status"] == "keep"
    # Recommendation and score must NOT change
    assert data["recommendation"] == "review"
    assert data["score"] == 75.0

    # Verify directly in database
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT status, recommendation FROM photos WHERE id = ?", (p2["id"],)).fetchone()
    conn.close()
    assert row[0] == "keep"
    assert row[1] == "review"

    # Validation: reject invalid status string
    res_bad = client.patch(f"/photos/{p2['id']}/status", json={"status": "super_keep"})
    assert res_bad.status_code == 400

    # Validation: 404 on non-existent photo
    res_404 = client.patch("/photos/non_existent_id/status", json={"status": "reject"})
    assert res_404.status_code == 404

    print("  [OK] test_single_photo_status_update passed")


def test_bulk_photo_status_update():
    batch_id, photos = setup_phase8_test_data()
    p1_id = photos[0]["id"]
    p3_id = photos[2]["id"]

    # Bulk update p1 and p3 to reject
    res = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"photo_ids": [p1_id, p3_id], "status": "reject"},
    )
    assert res.status_code == 200
    assert res.json()["updated_count"] == 2

    # Verify both changed to reject in DB
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, status FROM photos WHERE id IN (?, ?)", (p1_id, p3_id)
    ).fetchall()
    conn.close()
    assert all(r[1] == "reject" for r in rows)

    # Bulk update via filter (e.g. filter="blur")
    p4_id = photos[3]["id"]
    res_filt = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"filter": "blur", "status": "review"},
    )
    assert res_filt.status_code == 200
    assert res_filt.json()["updated_count"] >= 1

    conn = sqlite3.connect(DB_PATH)
    row_p4 = conn.execute("SELECT status FROM photos WHERE id = ?", (p4_id,)).fetchone()
    conn.close()
    assert row_p4[0] == "review"

    print("  [OK] test_bulk_photo_status_update passed")


def test_export_zip_stream():
    batch_id, photos = setup_phase8_test_data()
    # By default, p1 and p3 have status='keep'
    # p1 and p2 both have filename="img_same_name.jpg"

    # Set p1 and p2 both to 'keep' to test collision disambiguation
    client.patch(f"/photos/{photos[1]['id']}/status", json={"status": "keep"})

    res = client.post(f"/batches/{batch_id}/export", json={})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert f"photosort_{batch_id}_selected.zip" in res.headers.get("content-disposition", "")

    # Read zip bytes
    zip_bytes = io.BytesIO(res.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        # Should contain 3 files (p1, p2, p3)
        assert len(namelist) == 3
        # Collision check: one must be img_same_name.jpg and the other prefixed with photo_id
        assert "img_same_name.jpg" in namelist
        assert any("img_same_name.jpg" in name and name != "img_same_name.jpg" for name in namelist)
        assert "stage_show.jpg" in namelist

        # Verify data integrity
        content_p1 = zf.read("img_same_name.jpg")
        assert content_p1 == b"\xff\xd8\xff\xe0data_for_p1"

    # Export specific photo IDs including p4 (which has missing file on disk)
    res_partial = client.post(
        f"/batches/{batch_id}/export",
        json={"photo_ids": [photos[0]["id"], photos[3]["id"]]},
    )
    assert res_partial.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_partial.content), "r") as zf:
        # p4 was missing on disk, so only p1 was written
        assert len(zf.namelist()) == 1

    print("  [OK] test_export_zip_stream passed")


def test_export_csv_report():
    batch_id, photos = setup_phase8_test_data()

    res = client.get(f"/batches/{batch_id}/export/report")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert f"photosort_{batch_id}_report.csv" in res.headers.get("content-disposition", "")

    csv_text = res.text
    assert "=== BATCH CULLING SUMMARY ===" in csv_text
    assert "=== PER-PHOTO BREAKDOWN ===" in csv_text
    assert f"Batch ID,{batch_id}" in csv_text
    assert "Total Photos,4" in csv_text
    assert "Kept,2" in csv_text
    assert "Photo ID,Filename,Category,Score" in csv_text
    assert photos[0]["id"] in csv_text
    assert "img_same_name.jpg" in csv_text

    print("  [OK] test_export_csv_report passed")


if __name__ == "__main__":
    print("Running Phase 8 Backend Tests...")
    test_single_photo_status_update()
    test_bulk_photo_status_update()
    test_export_zip_stream()
    test_export_csv_report()
    print("\nALL PHASE 8 BACKEND TESTS PASSED!")
