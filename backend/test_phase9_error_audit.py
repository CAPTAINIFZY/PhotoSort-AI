from __future__ import annotations

import io
import os
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
"""
test_phase9_error_audit.py — Comprehensive error handling and edge-case audit.

Tests:
1. Broken test batch through /upload:
   a. Text file renamed to .jpg
   b. 0-byte file with .jpg extension
   c. Truncated / corrupt partial JPEG
   d. Extremely large image (8000x6000px)
   e. Image with multiple faces
   f. Image with zero faces (landscape)
2. Verify /upload isolates rejected files without aborting valid files.
3. Verify /analyze runs to completion without crashing on edge cases.
4. Verify GET /batches/{batch_id}/errors returns per-file reasons and stages.
5. Verify GET /batches/{batch_id}/summary reports total, processed, and failed_count.
"""

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from db import DB_PATH, init_db, get_batch_errors
from main import app, UPLOAD_DIR
from workers.job_runner import run_batch_analysis

client = TestClient(app)


def create_audit_files(tmp_dir: Path) -> dict[str, tuple[str, bytes, str]]:
    """Create test files for the error handling audit."""
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # a. Text file renamed to .jpg
    txt_content = b"This is plain text, not a JPEG image at all."
    
    # b. 0-byte file
    empty_content = b""

    # c. Corrupt / truncated JPEG header only
    truncated_content = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

    # d. Extremely large image (8000 x 6000)
    large_img = Image.new("RGB", (8000, 6000), color=(120, 140, 180))
    large_buf = io.BytesIO()
    large_img.save(large_buf, format="JPEG", quality=75)
    large_content = large_buf.getvalue()

    # e. Crowd / multi-face image (500x500 synthetic with multiple painted regions)
    crowd_img = np.full((600, 800, 3), 200, dtype=np.uint8)
    # Draw simple shapes to simulate features
    for x in range(50, 750, 60):
        cv2.circle(crowd_img, (x, 200), 20, (150, 180, 220), -1)
        cv2.circle(crowd_img, (x - 6, 195), 3, (40, 40, 40), -1)
        cv2.circle(crowd_img, (x + 6, 195), 3, (40, 40, 40), -1)
    _, crowd_buf = cv2.imencode(".jpg", crowd_img)
    crowd_content = crowd_buf.tobytes()

    # f. Zero faces landscape
    landscape_img = np.full((600, 800, 3), 100, dtype=np.uint8)
    cv2.rectangle(landscape_img, (0, 300), (800, 600), (40, 160, 40), -1)  # grass
    cv2.rectangle(landscape_img, (0, 0), (800, 300), (220, 180, 100), -1)  # sky
    _, land_buf = cv2.imencode(".jpg", landscape_img)
    landscape_content = land_buf.tobytes()

    return {
        "fake_text.jpg": ("fake_text.jpg", txt_content, "image/jpeg"),
        "zero_bytes.jpg": ("zero_bytes.jpg", empty_content, "image/jpeg"),
        "truncated.jpg": ("truncated.jpg", truncated_content, "image/jpeg"),
        "huge_8000x6000.jpg": ("huge_8000x6000.jpg", large_content, "image/jpeg"),
        "crowd_scene.jpg": ("crowd_scene.jpg", crowd_content, "image/jpeg"),
        "landscape_noface.jpg": ("landscape_noface.jpg", landscape_content, "image/jpeg"),
    }


def test_error_handling_audit():
    init_db()
    tmp_dir = ROOT / "processed" / "test_scratch"
    files_map = create_audit_files(tmp_dir)

    print("=== 1. Testing Multipart Upload with Broken & Edge-Case Files ===")
    upload_files = [
        ("files", (meta[0], io.BytesIO(meta[1]), meta[2]))
        for meta in files_map.values()
    ]

    res_upload = client.post("/upload", files=upload_files)
    assert res_upload.status_code == 200, f"Upload returned {res_upload.status_code}: {res_upload.text}"
    upload_data = res_upload.json()
    batch_id = upload_data["batch_id"]

    print(f"  Batch ID: {batch_id}")
    print(f"  Accepted count: {upload_data['accepted_count']}")
    print(f"  Rejected count: {upload_data['rejected_count']}")

    # Three broken files should be rejected
    rejected_names = {r["filename"] for r in upload_data["rejected"]}
    assert "fake_text.jpg" in rejected_names
    assert "zero_bytes.jpg" in rejected_names
    assert "truncated.jpg" in rejected_names
    assert upload_data["rejected_count"] == 3

    # Three valid edge-case files should be accepted
    accepted_names = {a["filename"] for a in upload_data["accepted"]}
    assert "huge_8000x6000.jpg" in accepted_names
    assert "crowd_scene.jpg" in accepted_names
    assert "landscape_noface.jpg" in accepted_names
    assert upload_data["accepted_count"] == 3

    print("  [OK] Upload isolated broken files and accepted edge-case images.")

    print("\n=== 2. Testing Analysis Pipeline Execution on Edge-Case Images ===")
    # Run analysis synchronously
    run_batch_analysis(batch_id)

    # Check status
    res_status = client.get(f"/batches/{batch_id}/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    print(f"  Job status: {status_data['status']}, processed: {status_data['processed']}, failed: {status_data['failed']}")
    assert status_data["status"] == "completed"
    assert status_data["processed"] == 3
    assert status_data["failed"] == 0

    print("  [OK] Pipeline completed on edge-case files without crashing.")

    print("\n=== 3. Testing GET /batches/{batch_id}/errors ===")
    res_errors = client.get(f"/batches/{batch_id}/errors")
    assert res_errors.status_code == 200
    errors_list = res_errors.json()
    print(f"  Total logged errors: {len(errors_list)}")
    assert len(errors_list) >= 3
    error_filenames = {e["filename"] for e in errors_list}
    assert "fake_text.jpg" in error_filenames
    assert "zero_bytes.jpg" in error_filenames
    assert "truncated.jpg" in error_filenames
    for e in errors_list:
        assert e["stage"] == "upload"
        assert e["reason"] == "corrupt_image"

    print("  [OK] GET /batches/{batch_id}/errors correctly surfaced per-file upload reasons.")

    print("\n=== 4. Testing GET /batches/{batch_id}/summary with failed_count ===")
    res_summary = client.get(f"/batches/{batch_id}/summary")
    assert res_summary.status_code == 200
    summary_data = res_summary.json()
    print(f"  Summary: total={summary_data['total']}, best_shots={summary_data['best_shots']}, failed_count={summary_data['failed_count']}")
    assert summary_data["total"] == 3
    assert summary_data["failed_count"] == 3  # 3 upload rejections recorded

    # Verify photos in DB have valid scores and categories
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT filename, score, composition_score, face_count, recommendation, status FROM photos WHERE batch_id = ?", (batch_id,)).fetchall()
    conn.close()
    assert len(rows) == 3
    for r in rows:
        fname, score, comp_score, face_cnt, rec, stat = r
        print(f"    - {fname}: score={score}, comp={comp_score}, faces={face_cnt}, rec={rec}, status={stat}")
        assert score is not None and score > 0
        assert comp_score is not None
        assert rec in ("keep", "review", "reject")

    print("  [OK] All accepted edge-case photos scored cleanly.")

    print("\n=== 5. Testing Mid-Pipeline Corrupt Image Fault Isolation ===")
    # Insert a photo directly into photos table with a corrupted file on disk to test CV failure isolation
    corrupt_id = f"corrupt_{uuid4().hex[:8]}"
    corrupt_path = Path(UPLOAD_DIR) / batch_id / f"{corrupt_id}.jpg"
    corrupt_path.write_bytes(b"CORRUPT_BYTES_NOT_IMAGE")

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO photos (id, batch_id, filename, status) VALUES (?, ?, ?, 'review')",
        (corrupt_id, batch_id, "corrupt_on_disk.jpg"),
    )
    conn.commit()
    conn.close()

    # Re-run analysis on the batch
    run_batch_analysis(batch_id)

    # Check status now reports 1 failed
    res_status2 = client.get(f"/batches/{batch_id}/status")
    status_data2 = res_status2.json()
    print(f"  Job status with corrupt photo: processed={status_data2['processed']}, failed={status_data2['failed']}")
    assert status_data2["failed"] == 1
    assert status_data2["processed"] == 3

    # Check GET /batches/{batch_id}/errors includes the CV analysis failure
    res_errors2 = client.get(f"/batches/{batch_id}/errors")
    cv_errors = [e for e in res_errors2.json() if e["stage"] == "cv_analysis"]
    assert len(cv_errors) == 1
    assert cv_errors[0]["filename"] == "corrupt_on_disk.jpg"
    assert "Cannot open image" in cv_errors[0]["reason"]
    print("  [OK] Corrupt file during CV analysis isolated cleanly; recorded in batch_errors.")

    print("\nALL ERROR AUDIT TESTS PASSED!")


if __name__ == "__main__":
    test_error_handling_audit()
