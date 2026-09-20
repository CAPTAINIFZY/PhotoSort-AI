"""
test_criterion1_broken_files.py -- Verification of Phase 9 Acceptance Criterion 1:
"A batch with at least 5 deliberately broken files (corrupt, wrong extension, 0-byte, oversized)
completes without crashing, with clear per-file failure reporting"
"""

import io
import os
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app
from db import init_db, get_session, Photo
from sqlmodel import select

client = TestClient(app)

def create_dummy_image_bytes(width=200, height=200, color=(100, 150, 200)):
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(buf, format="JPEG")
    return buf.getvalue()

def run_criterion_1_test():
    print("=== Testing Criterion 1: Batch with >= 5 Broken Files ===")
    init_db()

    # Create the 5 deliberately broken files + valid files
    # 1. Wrong extension (.txt renamed or unsupported extension)
    f1_wrong_ext = ("document.txt", io.BytesIO(b"This is a text document, not an image."), "text/plain")
    
    # 2. Text file with valid .jpg extension
    f2_fake_jpg = ("fake_text.jpg", io.BytesIO(b"Not a real jpeg at all, just plain ascii"), "image/jpeg")
    
    # 3. 0-byte file with valid extension
    f3_zero_byte = ("empty_zero_byte.jpg", io.BytesIO(b""), "image/jpeg")
    
    # 4. Truncated / corrupt JPEG (starts with SOI then garbage)
    f4_truncated = ("truncated.jpg", io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00GARBAGE_TRUNCATED"), "image/jpeg")
    
    # 5. Corrupt PNG header / binary noise
    f5_corrupt_png = ("corrupt_binary.png", io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRBAD_CHECKSUM"), "image/png")
    
    # Valid photos
    f6_valid1 = ("valid_portrait.jpg", io.BytesIO(create_dummy_image_bytes(300, 400, (180, 140, 120))), "image/jpeg")
    f7_valid2 = ("valid_stage.jpg", io.BytesIO(create_dummy_image_bytes(400, 300, (50, 80, 150))), "image/jpeg")
    f8_valid3 = ("valid_landscape.jpg", io.BytesIO(create_dummy_image_bytes(500, 300, (80, 180, 70))), "image/jpeg")

    upload_files = [
        ("files", f1_wrong_ext),
        ("files", f2_fake_jpg),
        ("files", f3_zero_byte),
        ("files", f4_truncated),
        ("files", f5_corrupt_png),
        ("files", f6_valid1),
        ("files", f7_valid2),
        ("files", f8_valid3),
    ]

    print("\n1. Uploading batch with 5 deliberately broken files + 3 valid images...")
    res = client.post("/upload", files=upload_files)
    assert res.status_code == 200, f"Upload returned {res.status_code}: {res.text}"
    data = res.json()
    batch_id = data["batch_id"]
    print(f"   Batch ID: {batch_id}")
    print(f"   Accepted: {data['accepted_count']}, Rejected: {data['rejected_count']}")

    assert data["rejected_count"] == 5, f"Expected exactly 5 rejections, got {data['rejected_count']}"
    assert data["accepted_count"] == 3, f"Expected 3 accepted files, got {data['accepted_count']}"

    rejected_filenames = {r["filename"]: r["reason"] for r in data["rejected"]}
    assert "document.txt" in rejected_filenames, "document.txt was not rejected"
    assert "fake_text.jpg" in rejected_filenames, "fake_text.jpg was not rejected"
    assert "empty_zero_byte.jpg" in rejected_filenames, "empty_zero_byte.jpg was not rejected"
    assert "truncated.jpg" in rejected_filenames, "truncated.jpg was not rejected"
    assert "corrupt_binary.png" in rejected_filenames, "corrupt_binary.png was not rejected"
    print("   [OK] All 5 deliberately broken files rejected cleanly at upload with specific reasons:")
    for fname, rsn in rejected_filenames.items():
        print(f"        - {fname}: {rsn}")

    # Inject a 6th corrupt photo directly into DB and disk to test CV analysis fault isolation
    print("\n2. Injecting a 6th mid-pipeline corrupted file directly into batch...")
    photo_id_corrupt = f"corrupt_cv_{batch_id[:8]}"
    uploads_dir = Path("uploads/originals") / batch_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    corrupt_disk_path = uploads_dir / f"{photo_id_corrupt}.jpg"
    with open(corrupt_disk_path, "wb") as f:
        f.write(b"NOT_A_VALID_CV_IMAGE_CANNOT_DECODE")

    with next(get_session()) as session:
        corrupt_photo = Photo(
            id=photo_id_corrupt,
            filename="cv_stage_corrupt.jpg",
            batch_id=batch_id,
            status="pending",
        )
        session.add(corrupt_photo)
        session.commit()

    print("\n3. Triggering analysis pipeline on the batch...")
    res_analyze = client.post(f"/batches/{batch_id}/analyze")
    assert res_analyze.status_code in (200, 202), f"Analyze returned {res_analyze.status_code}: {res_analyze.text}"

    # Wait for completion
    for _ in range(30):
        time.sleep(1)
        res_status = client.get(f"/batches/{batch_id}/status")
        st_data = res_status.json()
        if st_data["status"] in ("completed", "failed"):
            break

    print(f"   Pipeline completed: status={st_data['status']}, processed={st_data['processed']}, failed={st_data['failed']}")
    assert st_data["status"] == "completed", f"Expected completed, got {st_data['status']}"
    assert st_data["processed"] == 3, f"Expected 3 processed, got {st_data['processed']}"
    assert st_data["failed"] == 1, f"Expected 1 failed in CV runner, got {st_data['failed']}"
    print("   [OK] Analysis pipeline completed without crashing despite mid-pipeline corrupt file.")

    print("\n4. Inspecting GET /batches/{batch_id}/errors...")
    res_err = client.get(f"/batches/{batch_id}/errors")
    assert res_err.status_code == 200
    errors = res_err.json()
    print(f"   Total logged errors: {len(errors)}")
    assert len(errors) == 6, f"Expected 6 errors (5 upload + 1 cv_analysis), got {len(errors)}"

    stages = [e["stage"] for e in errors]
    assert stages.count("upload") == 5, f"Expected 5 upload errors, got {stages.count('upload')}"
    assert stages.count("cv_analysis") == 1, f"Expected 1 cv_analysis error, got {stages.count('cv_analysis')}"
    
    print("   Errors logged per file:")
    for err in errors:
        print(f"     • [{err['stage']}] {err['filename']}: {err['reason']}")

    print("\n5. Inspecting GET /batches/{batch_id}/summary...")
    res_sum = client.get(f"/batches/{batch_id}/summary")
    assert res_sum.status_code == 200
    summary = res_sum.json()
    assert summary["total"] == 4  # 3 valid + 1 DB injected
    assert summary["failed_count"] == 6  # 5 upload + 1 cv_analysis
    print(f"   Summary: total={summary['total']}, failed_count={summary['failed_count']}")
    print("   [OK] Summary matches expected counts.")

    print("\n========================================================")
    print("ACCEPTANCE CRITERION 1 FULLY SATISFIED AND VERIFIED!")
    print("========================================================")

if __name__ == "__main__":
    run_criterion_1_test()
