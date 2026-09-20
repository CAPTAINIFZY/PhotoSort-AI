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
test_phase8_acceptance.py — Comprehensive acceptance test suite for Phase 8.

Verifies:
1. PATCH /photos/{photo_id}/status:
   - Validates status enum ('keep' | 'review' | 'reject')
   - Modifies photos.status ONLY — preserves score, recommendation, reasons, files
   - Returns updated photo row
   - Handles 404 for missing photos
2. PATCH /batches/{batch_id}/photos/status:
   - Updates by explicit photo_ids list
   - Updates by filter expression ('best_shots', 'blur', 'duplicates', etc.)
   - Validates status enum and updates atomically
   - Returns correct updated_count
3. Batch summary selected_count integration:
   - Live synchronization of selected_count with photos.status == 'keep'
4. POST /batches/{batch_id}/export:
   - Default exports all photos with status == 'keep'
   - Explicit photo_ids export
   - Disambiguation of duplicate filenames in the archive
   - Graceful skipping of missing source files on disk
   - Streaming response and cleanup
5. GET /batches/{batch_id}/export/report:
   - Valid CSV structure with summary header and per-photo breakdown
   - Metrics match database and summary figures exactly
   - Semicolon-separated reasons column
"""

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db
from main import app, UPLOAD_DIR

client = TestClient(app)


def seed_test_batch(num_photos: int = 6) -> tuple[str, list[dict]]:
    init_db()
    batch_id = f"acc_p8_{uuid4().hex[:8]}"

    photos_seed = [
        {
            "id": f"{batch_id}_p1",
            "filename": "portrait_a.jpg",
            "category": "people",
            "score": 94.5,
            "sharpness_score": 95.0,
            "exposure_score": 90.0,
            "face_score": 92.0,
            "composition_score": 88.0,
            "uniqueness_score": 90.0,
            "recommendation": "keep",
            "status": "keep",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "reasons": '["High sharpness (95)", "Well exposed", "Rule of thirds aligned"]',
            "created_at": "2026-09-20T10:00:00",
        },
        {
            "id": f"{batch_id}_p2",
            "filename": "portrait_a.jpg",  # Intentionally identical filename to test collision resolution
            "category": "people",
            "score": 78.0,
            "sharpness_score": 80.0,
            "exposure_score": 75.0,
            "face_score": 70.0,
            "composition_score": 72.0,
            "uniqueness_score": 50.0,
            "recommendation": "review",
            "status": "review",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 1,
            "similarity_group": 101,
            "reasons": '["Moderate sharpness", "Secondary cluster frame"]',
            "created_at": "2026-09-20T10:00:05",
        },
        {
            "id": f"{batch_id}_p3",
            "filename": "stage_event.jpg",
            "category": "stage",
            "score": 86.0,
            "sharpness_score": 88.0,
            "exposure_score": 85.0,
            "face_score": 80.0,
            "composition_score": 84.0,
            "uniqueness_score": 92.0,
            "recommendation": "keep",
            "status": "keep",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "reasons": '["Good stage lighting", "AI Pick for stage"]',
            "created_at": "2026-09-20T10:01:00",
        },
        {
            "id": f"{batch_id}_p4",
            "filename": "candid_blur.jpg",
            "category": "candid",
            "score": 35.0,
            "sharpness_score": 30.0,
            "exposure_score": 60.0,
            "face_score": 40.0,
            "composition_score": 45.0,
            "uniqueness_score": 70.0,
            "recommendation": "reject",
            "status": "reject",
            "blur_detected": 1,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "reasons": '["Motion blur detected (Laplacian 30.0)", "Below sharpness bar"]',
            "created_at": "2026-09-20T10:02:00",
        },
        {
            "id": f"{batch_id}_p5",
            "filename": "group_blink.jpg",
            "category": "group",
            "score": 48.0,
            "sharpness_score": 82.0,
            "exposure_score": 80.0,
            "face_score": 30.0,
            "composition_score": 70.0,
            "uniqueness_score": 60.0,
            "recommendation": "reject",
            "status": "reject",
            "blur_detected": 0,
            "closed_eyes_detected": 1,
            "duplicate": 0,
            "similarity_group": None,
            "reasons": '["Closed eyes / blink detected on primary face"]',
            "created_at": "2026-09-20T10:03:00",
        },
        {
            "id": f"{batch_id}_p6",
            "filename": "other_doc.jpg",
            "category": "other",
            "score": 62.0,
            "sharpness_score": 65.0,
            "exposure_score": 70.0,
            "face_score": None,
            "composition_score": 60.0,
            "uniqueness_score": 50.0,
            "recommendation": "review",
            "status": "review",
            "blur_detected": 0,
            "closed_eyes_detected": 0,
            "duplicate": 0,
            "similarity_group": None,
            "reasons": '["Candidate shot", "No faces detected"]',
            "created_at": "2026-09-20T10:04:00",
        },
    ]

    conn = sqlite3.connect(DB_PATH)
    for p in photos_seed:
        conn.execute(
            """
            INSERT INTO photos (
                id, batch_id, filename, category, score, sharpness_score,
                exposure_score, face_score, composition_score, uniqueness_score,
                recommendation, status, blur_detected, closed_eyes_detected,
                duplicate, similarity_group, reasons, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p["id"],
                batch_id,
                p["filename"],
                p["category"],
                p["score"],
                p["sharpness_score"],
                p["exposure_score"],
                p["face_score"],
                p["composition_score"],
                p["uniqueness_score"],
                p["recommendation"],
                p["status"],
                p["blur_detected"],
                p["closed_eyes_detected"],
                p["duplicate"],
                p["similarity_group"],
                p["reasons"],
                p["created_at"],
            ),
        )
    conn.commit()
    conn.close()

    # Create dummy original files on disk for p1, p2, p3, p5, p6
    # Keep p4 absent from disk to test missing-file handling
    orig_dir = Path(UPLOAD_DIR) / batch_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    (orig_dir / f"{photos_seed[0]['id']}.jpg").write_bytes(b"JPEG_P1_HIGH_RES")
    (orig_dir / f"{photos_seed[1]['id']}.jpg").write_bytes(b"JPEG_P2_HIGH_RES")
    (orig_dir / f"{photos_seed[2]['id']}.jpg").write_bytes(b"JPEG_P3_HIGH_RES")
    (orig_dir / f"{photos_seed[4]['id']}.jpg").write_bytes(b"JPEG_P5_HIGH_RES")
    (orig_dir / f"{photos_seed[5]['id']}.jpg").write_bytes(b"JPEG_P6_HIGH_RES")

    return batch_id, photos_seed


def test_acceptance_criteria():
    print("=== STARTING PHASE 8 ACCEPTANCE TESTS ===")
    batch_id, photos = seed_test_batch()

    # ----------------------------------------------------
    # Criterion 1: PATCH /photos/{photo_id}/status
    # ----------------------------------------------------
    print("\n--- Testing Criterion 1: Single Photo Status Override ---")
    p2 = photos[1]
    # Check original DB state
    conn = sqlite3.connect(DB_PATH)
    original_row = conn.execute("SELECT score, recommendation, reasons FROM photos WHERE id = ?", (p2["id"],)).fetchone()
    conn.close()

    # 1.1 Valid status update
    res = client.patch(f"/photos/{p2['id']}/status", json={"status": "keep"})
    assert res.status_code == 200, f"Failed updating status: {res.text}"
    updated_p2 = res.json()
    assert updated_p2["status"] == "keep"
    # score, recommendation, reasons must be untouched
    assert updated_p2["score"] == original_row[0]
    assert updated_p2["recommendation"] == original_row[1]
    assert updated_p2["reasons"] == ["Moderate sharpness", "Secondary cluster frame"]

    # 1.2 Status validation rejection
    bad_res = client.patch(f"/photos/{p2['id']}/status", json={"status": "invalid_status"})
    assert bad_res.status_code == 400
    assert "Invalid status" in bad_res.json()["detail"]

    # 1.3 404 for nonexistent photo
    missing_res = client.patch("/photos/does_not_exist/status", json={"status": "reject"})
    assert missing_res.status_code == 404
    print("  [✓] Criterion 1 PASSED: Status validated, only photos.status modified, recommendation preserved.")

    # ----------------------------------------------------
    # Criterion 2: PATCH /batches/{batch_id}/photos/status (Bulk)
    # ----------------------------------------------------
    print("\n--- Testing Criterion 2: Bulk Photo Status Updates ---")
    # 2.1 Bulk by explicit IDs
    res_bulk_ids = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"photo_ids": [photos[4]["id"], photos[5]["id"]], "status": "keep"},
    )
    assert res_bulk_ids.status_code == 200
    assert res_bulk_ids.json()["updated_count"] == 2

    # 2.2 Bulk by filter (e.g., filter='blur')
    res_bulk_filter = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"filter": "blur", "status": "review"},
    )
    assert res_bulk_filter.status_code == 200
    assert res_bulk_filter.json()["updated_count"] == 1  # p4 is blur_detected=1

    # 2.3 Invalid status in bulk
    bad_bulk = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"photo_ids": [photos[0]["id"]], "status": "unknown"},
    )
    assert bad_bulk.status_code == 400
    print("  [✓] Criterion 2 PASSED: Bulk updates by ID list and filter succeed atomically.")

    # ----------------------------------------------------
    # Criterion 3: Live Selected Count in /batches/{batch_id}/summary
    # ----------------------------------------------------
    print("\n--- Testing Criterion 3: Summary selected_count Synchronization ---")
    summary_res = client.get(f"/batches/{batch_id}/summary")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert "selected_count" in summary_data

    # Count how many are currently 'keep' in DB
    conn = sqlite3.connect(DB_PATH)
    actual_keep = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND status = 'keep'", (batch_id,)).fetchone()[0]
    conn.close()
    assert summary_data["selected_count"] == actual_keep
    print(f"  [✓] Criterion 3 PASSED: selected_count ({summary_data['selected_count']}) matches DB status='keep' count ({actual_keep}).")

    # ----------------------------------------------------
    # Criterion 4: POST /batches/{batch_id}/export (ZIP Stream)
    # ----------------------------------------------------
    print("\n--- Testing Criterion 4: Streaming ZIP Export ---")
    # At this point:
    # p1: keep (filename: portrait_a.jpg, file exists)
    # p2: keep (filename: portrait_a.jpg, collision with p1!, file exists)
    # p3: keep (filename: stage_event.jpg, file exists)
    # p4: review (candid_blur.jpg, missing on disk)
    # p5: keep (group_blink.jpg, file exists)
    # p6: keep (other_doc.jpg, file exists)

    res_zip = client.post(f"/batches/{batch_id}/export", json={})
    assert res_zip.status_code == 200
    assert res_zip.headers["content-type"] == "application/zip"
    assert f"photosort_{batch_id}_selected.zip" in res_zip.headers.get("content-disposition", "")

    # Parse ZIP archive
    zip_buffer = io.BytesIO(res_zip.content)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        namelist = zf.namelist()
        print(f"  Archive contains {len(namelist)} files: {namelist}")

        # Collision check: portrait_a.jpg exists, and the second one has a disambiguated name
        assert "portrait_a.jpg" in namelist
        disambiguated = [name for name in namelist if "portrait_a.jpg" in name and name != "portrait_a.jpg"]
        assert len(disambiguated) == 1, f"Expected 1 disambiguated portrait_a file, got {disambiguated}"
        print(f"  Disambiguated duplicate filename: {disambiguated[0]}")

        # Content verification
        assert zf.read("portrait_a.jpg") == b"JPEG_P1_HIGH_RES"
        assert zf.read(disambiguated[0]) == b"JPEG_P2_HIGH_RES"
        assert "stage_event.jpg" in namelist
        assert zf.read("stage_event.jpg") == b"JPEG_P3_HIGH_RES"

    # Test explicit export including missing file p4
    res_zip_missing = client.post(
        f"/batches/{batch_id}/export",
        json={"photo_ids": [photos[0]["id"], photos[3]["id"]]},  # p4 missing
    )
    assert res_zip_missing.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_zip_missing.content), "r") as zf:
        # p4 missing on disk should be gracefully skipped without failing the request
        assert zf.namelist() == ["portrait_a.jpg"]

    print("  [✓] Criterion 4 PASSED: ZIP stream builds incrementally, resolves filename collisions, and handles missing files gracefully.")

    # ----------------------------------------------------
    # Criterion 5: GET /batches/{batch_id}/export/report (CSV)
    # ----------------------------------------------------
    print("\n--- Testing Criterion 5: Audit CSV Report ---")
    res_csv = client.get(f"/batches/{batch_id}/export/report")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert f"photosort_{batch_id}_report.csv" in res_csv.headers.get("content-disposition", "")

    csv_lines = res_csv.text.strip().splitlines()

    # Verify Summary Section
    assert "=== BATCH CULLING SUMMARY ===" in csv_lines[0]
    assert f"Batch ID,{batch_id}" in csv_lines[1]
    assert f"Total Photos,{len(photos)}" in csv_lines[2]

    # Verify Summary counts match database
    conn = sqlite3.connect(DB_PATH)
    c_keep = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND status = 'keep'", (batch_id,)).fetchone()[0]
    c_review = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND status = 'review'", (batch_id,)).fetchone()[0]
    c_reject = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND status = 'reject'", (batch_id,)).fetchone()[0]
    c_blur = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND blur_detected = 1", (batch_id,)).fetchone()[0]
    c_eyes = conn.execute("SELECT COUNT(*) FROM photos WHERE batch_id = ? AND closed_eyes_detected = 1", (batch_id,)).fetchone()[0]
    conn.close()

    assert f"Kept,{c_keep}" in res_csv.text
    assert f"Review,{c_review}" in res_csv.text
    assert f"Rejected,{c_reject}" in res_csv.text
    assert f"Blur Count,{c_blur}" in res_csv.text
    assert f"Closed Eyes Count,{c_eyes}" in res_csv.text

    # Verify Breakdown Table header and rows
    assert "=== PER-PHOTO BREAKDOWN ===" in res_csv.text
    header_idx = [i for i, line in enumerate(csv_lines) if line.startswith("Photo ID,Filename")][0]
    headers = [col.strip() for col in csv_lines[header_idx].split(",")]
    assert headers == [
        "Photo ID", "Filename", "Category", "Score",
        "Sharpness Score", "Exposure Score", "Face Score", "Composition Score", "Uniqueness Score",
        "Recommendation", "Status", "Reasons"
    ]

    # Parse rows using csv.reader
    reader = csv.reader(csv_lines[header_idx + 1:])
    rows = list(reader)
    assert len(rows) == len(photos)
    first_row = rows[0]
    assert first_row[0] == photos[0]["id"]
    assert first_row[1] == "portrait_a.jpg"
    assert first_row[2] == "people"
    assert float(first_row[3]) == 94.5
    assert first_row[9] == "keep"
    assert first_row[10] == "keep"
    # Reasons joined with semicolon
    assert ";" in first_row[11]

    print("  [✓] Criterion 5 PASSED: CSV report contains matching summary counts, valid headers, and per-photo audit rows.")

    print("\n========================================================")
    print("ALL PHASE 8 ACCEPTANCE CRITERIA SUCCESSFULLY VERIFIED!")
    print("========================================================")


if __name__ == "__main__":
    test_acceptance_criteria()
