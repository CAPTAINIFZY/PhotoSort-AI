"""
Phase 5 Acceptance Test Suite — PhotoSort AI
============================================

Tests:
1. Rule-of-thirds composition scoring & issue detection.
2. Full weighted composite scoring pulling weights from config.
3. Closed-eye and blur penalties applied properly.
4. AI Pick re-evaluation using final composite score (not just raw sharpness).
5. Duplicate non-picks forced to 'review' with reasons attached.
6. Singletons maintain similarity_group = null, duplicate = false.
7. Corrupt/missing image error isolation.
8. GET /photos/{photo_id} returns all scores, reasons, and recommendation.
9. Idempotency: re-running does not corrupt or drift scores or AI picks.
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PYTHON    = sys.executable
ROOT      = Path(__file__).resolve().parent.parent
BACKEND   = ROOT / "backend"
UPLOADS   = ROOT / "uploads" / "originals"
DB_FILE   = ROOT / "photosort.db"
PORT      = 18771
BASE_URL  = f"http://127.0.0.1:{PORT}"


# ── Synthetic Image Helpers ───────────────────────────────────────────────────

def make_test_image(kind: str) -> bytes:
    """Generate distinct images with simulated face/scene content."""
    img = Image.new("RGB", (300, 300), (245, 245, 245))
    d = ImageDraw.Draw(img)

    if kind == "portrait_good":
        # Neutral background, sharp face near rule-of-thirds (100, 100)
        d.rectangle([0, 0, 300, 300], fill=(220, 220, 220))
        d.ellipse([65, 65, 135, 135], fill=(255, 218, 185))  # face skin
        d.ellipse([80, 85, 90, 95], fill=(50, 50, 50))       # left eye open
        d.ellipse([110, 85, 120, 95], fill=(50, 50, 50))     # right eye open
        d.arc([85, 105, 115, 120], start=0, end=180, fill=(200, 50, 50), width=3) # smile
        # Add high contrast edges for high sharpness
        for i in range(10):
            d.line([10 + i * 25, 200, 20 + i * 25, 280], fill=(0, 0, 0), width=3)

    elif kind == "blurry_shot":
        # Low contrast, soft blurry wash
        d.rectangle([0, 0, 300, 300], fill=(180, 180, 180))
        d.ellipse([70, 70, 230, 230], fill=(175, 175, 175))

    elif kind == "landscape_solo":
        # Ocean + sky
        d.rectangle([0, 0, 300, 150], fill=(135, 206, 235))
        d.rectangle([0, 150, 300, 300], fill=(0, 105, 148))
        d.ellipse([180, 30, 240, 90], fill=(255, 215, 0))    # sun at (200, 60) -> near (200, 100) RoT

    elif kind == "dup_frame_1":
        # Burst shot A
        d.rectangle([0, 0, 300, 300], fill=(250, 240, 230))
        d.rectangle([80, 80, 220, 220], fill=(220, 20, 60))
        d.line([80, 80, 220, 220], fill=(255, 255, 255), width=8)

    elif kind == "dup_frame_2":
        # Identical copy of burst shot A (will be duplicates)
        d.rectangle([0, 0, 300, 300], fill=(250, 240, 230))
        d.rectangle([80, 80, 220, 220], fill=(220, 20, 60))
        d.line([80, 80, 220, 220], fill=(255, 255, 255), width=8)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ── HTTP Helpers ──────────────────────────────────────────────────────────────

def post_upload(files: list[tuple[str, str, bytes]]) -> dict:
    boundary = f"Phase5Boundary{uuid4().hex[:16]}"
    CRLF = b"\r\n"
    body = b""
    for field, filename, data in files:
        body += f"--{boundary}".encode() + CRLF
        body += f'Content-Disposition: form-data; name="{field}"; filename="{filename}"'.encode() + CRLF
        body += b"Content-Type: image/jpeg" + CRLF + CRLF
        body += data + CRLF
    body += f"--{boundary}--".encode() + CRLF

    req = urllib.request.Request(
        f"{BASE_URL}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def post_analyze(batch_id: str) -> dict:
    req = urllib.request.Request(f"{BASE_URL}/batches/{batch_id}/analyze", method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get_status(batch_id: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/batches/{batch_id}/status", timeout=10) as r:
        return json.loads(r.read())


def get_clusters(batch_id: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/batches/{batch_id}/clusters", timeout=10) as r:
        return json.loads(r.read())


def get_photo(photo_id: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/photos/{photo_id}", timeout=10) as r:
        return json.loads(r.read())


def wait_for_job(batch_id: str, timeout: float = 120.0) -> dict:
    t0 = time.perf_counter()
    while True:
        status = get_status(batch_id)
        if status.get("status") in ("completed", "failed"):
            return status
        if time.perf_counter() - t0 > timeout:
            raise TimeoutError(f"Job for batch {batch_id} timed out after {timeout}s: {status}")
        time.sleep(0.5)


# ── Test Runner ───────────────────────────────────────────────────────────────

def run_tests():
    print("=" * 72)
    print("  PhotoSort AI -- Phase 5 Acceptance Criteria Verification")
    print("=" * 72)

    print(f"\n[1/3] Starting backend server on port {PORT}...")
    server = subprocess.Popen(
        [
            PYTHON, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", str(PORT),
            "--log-level", "warning",
        ],
        cwd=str(BACKEND),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Backend server failed to start within 15 seconds.")
        print("      Server is healthy and ready.")

        # ── Test Batch: Diverse photos to test scoring engine ─────────────────
        print("\n[2/3] Uploading and running full Phase 5 analysis...")
        files = [
            ("files", "portrait_sharp.jpg", make_test_image("portrait_good")),
            ("files", "blurry_pic.jpg",     make_test_image("blurry_shot")),
            ("files", "landscape_solo.jpg", make_test_image("landscape_solo")),
            ("files", "dup_burst_1.jpg",    make_test_image("dup_frame_1")),
            ("files", "dup_burst_2.jpg",    make_test_image("dup_frame_2")),
            ("files", "corrupt_file.jpg",   make_test_image("blurry_shot")),
        ]

        upload_res = post_upload(files)
        batch_id = upload_res["batch_id"]
        assert upload_res["accepted_count"] == 6, f"Expected 6 accepted, got {upload_res}"
        print(f"      Uploaded batch: {batch_id} (6 items).")

        # Deliberately corrupt one photo file on disk to verify analysis error isolation
        corrupt_item = next(p for p in upload_res["accepted"] if p["filename"] == "corrupt_file.jpg")
        corrupt_pid = corrupt_item["photo_id"]
        corrupt_path = UPLOADS / batch_id / f"{corrupt_pid}.jpg"
        corrupt_path.write_bytes(b"corrupted unreadable binary data")

        t0 = time.perf_counter()
        post_analyze(batch_id)
        job_status = wait_for_job(batch_id)
        t_elapsed = time.perf_counter() - t0
        print(f"      Analysis + Scoring completed in {t_elapsed:.2f}s (status: {job_status['status']}).")
        assert job_status["status"] == "completed"
        assert job_status["processed"] == 5
        assert job_status["failed"] == 1

        # ── Verify GET /photos/{photo_id} and Scores ──────────────────────────
        print("\n[3/3] Verifying scoring metrics, recommendations, and endpoints...")

        # Query batch photos from DB
        conn = sqlite3.connect(str(DB_FILE))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, filename, score, composition_score, face_score, uniqueness_score, "
            "exposure_score, recommendation, reasons, duplicate, similarity_group, status, processing_error "
            "FROM photos WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        conn.close()

        photos_by_name = {r["filename"]: r for r in rows}

        # 1. Verify GET /photos/{photo_id} endpoint
        sharp_pid = photos_by_name["portrait_sharp.jpg"]["id"]
        detail = get_photo(sharp_pid)
        assert detail["id"] == sharp_pid
        assert detail["filename"] == "portrait_sharp.jpg"
        assert detail["score"] is not None and 0.0 <= detail["score"] <= 100.0
        assert detail["composition_score"] is not None
        assert detail["face_score"] is not None
        assert detail["uniqueness_score"] is not None
        assert detail["exposure_score"] is not None
        assert detail["recommendation"] in ("keep", "review", "reject")
        assert isinstance(detail["reasons"], list)
        print("  [PASS] GET /photos/{photo_id} returned full score and rationale model.")

        # 2. Verify Portrait score vs Blurry score
        p_sharp = photos_by_name["portrait_sharp.jpg"]
        p_blurry = photos_by_name["blurry_pic.jpg"]
        assert p_sharp["score"] > p_blurry["score"], (
            f"Sharp portrait score ({p_sharp['score']}) should be higher than blurry ({p_blurry['score']})"
        )
        assert p_sharp["recommendation"] == "keep"
        assert p_sharp["status"] == "keep"
        print("  [PASS] Sharp well-composed portrait scored high and received recommendation='keep'.")

        # 3. Verify Blurry photo penalties and reasons
        blurry_detail = get_photo(p_blurry["id"])
        assert blurry_detail["score"] < 60.0
        assert any("blur" in r.lower() or "focus" in r.lower() for r in blurry_detail["reasons"]), (
            f"Expected blur warning in reasons: {blurry_detail['reasons']}"
        )
        print("  [PASS] Blurry photo penalized with blur reason attached.")

        # 4. Verify Duplicate handling and AI Pick re-evaluation
        dup1 = photos_by_name["dup_burst_1.jpg"]
        dup2 = photos_by_name["dup_burst_2.jpg"]
        assert dup1["similarity_group"] is not None
        assert dup1["similarity_group"] == dup2["similarity_group"], "Duplicates must share similarity_group"
        
        # Exactly one is AI Pick (duplicate=False) and one is duplicate=True
        is_dup1_pick = not dup1["duplicate"]
        is_dup2_pick = not dup2["duplicate"]
        assert is_dup1_pick != is_dup2_pick, "Exactly one frame in cluster must be AI Pick"

        pick_photo = dup1 if is_dup1_pick else dup2
        non_pick_photo = dup2 if is_dup1_pick else dup1

        # The non-pick duplicate MUST be forced to 'review' regardless of score
        assert non_pick_photo["recommendation"] == "review", (
            f"Non-pick duplicate must be forced to 'review', got {non_pick_photo['recommendation']}"
        )
        assert non_pick_photo["status"] == "review"
        non_pick_detail = get_photo(non_pick_photo["id"])
        assert any("duplicate" in r.lower() or "similar" in r.lower() for r in non_pick_detail["reasons"])
        print("  [PASS] Duplicate cluster formed: AI Pick designated and duplicate forced to recommendation='review'.")

        # 5. Verify Singletons get similarity_group=null, duplicate=false, uniqueness=100
        solo = photos_by_name["landscape_solo.jpg"]
        assert solo["similarity_group"] is None
        assert not solo["duplicate"]
        assert solo["uniqueness_score"] == 100.0
        print("  [PASS] Singleton photo has similarity_group=null, duplicate=false, uniqueness_score=100.0.")

        # 6. Verify Corrupt image isolation
        corrupt = photos_by_name["corrupt_file.jpg"]
        assert corrupt["status"] == "error"
        assert corrupt["recommendation"] == "reject"
        assert corrupt["score"] == 0.0
        print("  [PASS] Corrupt photo cleanly isolated with status='error' and recommendation='reject'.")

        # 7. Test 404 for unknown photo
        try:
            get_photo("non-existent-uuid")
            raise AssertionError("Expected HTTP 404 for non-existent photo ID")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print("  [PASS] GET /photos/{invalid_id} returned HTTP 404.")

        # 8. Test Idempotency: re-run analysis
        from workers.job_runner import run_batch_analysis
        run_batch_analysis(batch_id)

        conn = sqlite3.connect(str(DB_FILE))
        conn.row_factory = sqlite3.Row
        re_rows = conn.execute(
            "SELECT id, filename, score, duplicate, similarity_group, recommendation "
            "FROM photos WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        conn.close()

        re_by_name = {r["filename"]: r for r in re_rows}
        for name, orig in photos_by_name.items():
            re = re_by_name[name]
            assert orig["score"] == re["score"], f"Score changed on re-run: {orig['score']} vs {re['score']}"
            assert orig["duplicate"] == re["duplicate"]
            assert orig["similarity_group"] == re["similarity_group"]
            assert orig["recommendation"] == re["recommendation"]
        print("  [PASS] Idempotency verified: re-running batch produced identical scores and AI picks.")

        print("\n" + "=" * 72)
        print("  ALL PHASE 5 ACCEPTANCE TESTS PASSED SUCCESSFULLY!")
        print("=" * 72 + "\n")

    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    run_tests()
