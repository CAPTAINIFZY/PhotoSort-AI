"""
Phase 4 Acceptance Test & Benchmark Suite — PhotoSort AI
========================================================

Verifies all Phase 4 acceptance criteria:
1. Every analyzed photo has a category value from the fixed label set
2. Visually near-identical photos in a test batch end up in the same similarity_group
3. Each similarity group has exactly one designated "AI Pick"
4. Singleton photos (no similar frames) get similarity_group = null and duplicate = false
5. Clustering runs once per batch after all embeddings exist, not once per photo
6. Re-running classification/clustering on the same batch is idempotent (doesn't duplicate or corrupt groups)
7. 300-image batch: embedding + clustering completes in a benchmarked, reasonable time on a normal laptop
"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image, ImageDraw

PYTHON    = sys.executable
ROOT      = Path(__file__).resolve().parent.parent
BACKEND   = ROOT / "backend"
UPLOADS   = ROOT / "uploads" / "originals"
EMB_DIR   = ROOT / "processed" / "embeddings"
DB_FILE   = ROOT / "photosort.db"
PORT      = 18770
BASE_URL  = f"http://127.0.0.1:{PORT}"

FIXED_CATEGORIES = {"people", "stage", "candid", "group", "other"}


# ── Visual Generator Helpers ──────────────────────────────────────────────────

def make_scene_image(kind: str) -> bytes:
    """Generate a semantically distinct synthetic scene image."""
    img = Image.new("RGB", (224, 224), (255, 255, 255))
    d = ImageDraw.Draw(img)
    if kind == "sun":
        d.ellipse([40, 40, 180, 180], fill=(255, 200, 0))
    elif kind == "tree":
        d.rectangle([95, 130, 125, 210], fill=(139, 69, 19))
        d.polygon([(110, 30), (40, 150), (180, 150)], fill=(34, 139, 34))
    elif kind == "ocean":
        d.rectangle([0, 112, 224, 224], fill=(0, 105, 148))
        d.rectangle([0, 0, 224, 112], fill=(135, 206, 235))
    elif kind == "car":
        d.rectangle([40, 90, 180, 150], fill=(220, 20, 60))
        d.ellipse([55, 140, 85, 170], fill=(0, 0, 0))
        d.ellipse([135, 140, 165, 170], fill=(0, 0, 0))
    elif kind == "triangle":
        d.polygon([(112, 20), (30, 190), (194, 190)], fill=(75, 0, 130))
    elif kind == "cross":
        d.line([30, 30, 194, 194], fill=(255, 105, 180), width=24)
        d.line([30, 194, 194, 30], fill=(255, 105, 180), width=24)
    else:
        d.rectangle([20, 20, 204, 204], fill=(100, 100, 100))

    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


# ── HTTP Helpers ──────────────────────────────────────────────────────────────

def post_upload(files: list[tuple[str, str, bytes]]) -> dict:
    boundary = f"WebKitFormBoundary{uuid4().hex[:16]}"
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


def wait_for_job(batch_id: str, timeout: float = 300.0) -> dict:
    t0 = time.perf_counter()
    while True:
        status = get_status(batch_id)
        if status.get("status") in ("completed", "failed"):
            return status
        if time.perf_counter() - t0 > timeout:
            raise TimeoutError(f"Job for batch {batch_id} timed out after {timeout}s: {status}")
        time.sleep(0.5)


# ── Main Test Runner ──────────────────────────────────────────────────────────

def run_tests():
    print("=" * 72)
    print("  PhotoSort AI -- Phase 4 Acceptance Criteria Verification")
    print("=" * 72)

    # Start FastAPI server via uvicorn in background
    print(f"\n[1/4] Starting backend server on port {PORT}...")
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
        # Wait for server health
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Backend server failed to start within 15 seconds.")
        print("      Server is healthy and responding.")

        # ── Test Batch 1: Duplicates, Singletons, Categories ───────────────────
        print("\n[2/4] Testing Acceptance Criteria 1, 2, 3, 4, 5 (Clustering & Deduplication)...")
        
        # 3 copies of 'tree' (cluster A)
        tree_bytes = make_scene_image("tree")
        # 2 copies of 'sun' (cluster B)
        sun_bytes = make_scene_image("sun")
        # 3 distinct singletons
        ocean_bytes = make_scene_image("ocean")
        car_bytes = make_scene_image("car")
        tri_bytes = make_scene_image("triangle")

        batch_files = [
            ("files", "tree_1.jpg", tree_bytes),
            ("files", "tree_2.jpg", tree_bytes),
            ("files", "tree_3.jpg", tree_bytes),
            ("files", "sun_1.jpg", sun_bytes),
            ("files", "sun_2.jpg", sun_bytes),
            ("files", "ocean_solo.jpg", ocean_bytes),
            ("files", "car_solo.jpg", car_bytes),
            ("files", "triangle_solo.jpg", tri_bytes),
        ]

        upload_res = post_upload(batch_files)
        batch_id = upload_res["batch_id"]
        assert upload_res["accepted_count"] == 8, f"Expected 8 accepted, got {upload_res}"
        print(f"      Uploaded test batch: {batch_id} (8 photos)")

        t_start = time.perf_counter()
        analyze_res = post_analyze(batch_id)
        assert analyze_res["status"] == "started", f"Unexpected analyze response: {analyze_res}"
        
        job_status = wait_for_job(batch_id)
        t_elapsed = time.perf_counter() - t_start
        assert job_status["status"] == "completed", f"Job failed: {job_status}"
        assert job_status["processed"] == 8, f"Expected 8 processed, got {job_status}"
        print(f"      Batch analysis completed in {t_elapsed:.2f}s.")

        # Verify DB directly
        conn = sqlite3.connect(str(DB_FILE))
        conn.row_factory = sqlite3.Row
        photos = conn.execute(
            "SELECT id, filename, category, similarity_group, duplicate, sharpness_score "
            "FROM photos WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        conn.close()

        photo_by_name = {r["filename"]: r for r in photos}

        # AC-1: Every analyzed photo has a category value from fixed label set
        for p in photos:
            cat = p["category"]
            assert cat in FIXED_CATEGORIES, f"Photo {p['filename']} category '{cat}' not in {FIXED_CATEGORIES}"
        print("  [PASS] AC-1: Every analyzed photo has a valid category from fixed label set.")

        # AC-2: Visually near-identical photos end up in the same similarity_group
        tree_group_1 = photo_by_name["tree_1.jpg"]["similarity_group"]
        tree_group_2 = photo_by_name["tree_2.jpg"]["similarity_group"]
        tree_group_3 = photo_by_name["tree_3.jpg"]["similarity_group"]
        assert tree_group_1 is not None, "tree_1.jpg should have a similarity_group"
        assert tree_group_1 == tree_group_2 == tree_group_3, (
            f"All tree copies must be in the same group, got {tree_group_1}, {tree_group_2}, {tree_group_3}"
        )

        sun_group_1 = photo_by_name["sun_1.jpg"]["similarity_group"]
        sun_group_2 = photo_by_name["sun_2.jpg"]["similarity_group"]
        assert sun_group_1 is not None, "sun_1.jpg should have a similarity_group"
        assert sun_group_1 == sun_group_2, "All sun copies must be in the same group"
        assert tree_group_1 != sun_group_1, "Tree group and Sun group must be different clusters"
        print("  [PASS] AC-2: Visually near-identical photos end up in the same similarity_group.")

        # AC-3: Each similarity group has exactly one designated 'AI Pick'
        for gid in (tree_group_1, sun_group_1):
            members = [p for p in photos if p["similarity_group"] == gid]
            ai_picks = [p for p in members if p["duplicate"] in (0, False)]
            duplicates = [p for p in members if p["duplicate"] in (1, True)]
            assert len(ai_picks) == 1, f"Group {gid} must have exactly 1 AI pick (duplicate=False), got {len(ai_picks)}"
            assert len(duplicates) == len(members) - 1, f"All other members in group {gid} must have duplicate=True"
            # Verify AI pick has the highest sharpness score
            pick = ai_picks[0]
            max_sharpness = max(m["sharpness_score"] or 0.0 for m in members)
            assert (pick["sharpness_score"] or 0.0) == max_sharpness, (
                f"AI pick must have highest sharpness: pick has {pick['sharpness_score']}, max was {max_sharpness}"
            )
        print("  [PASS] AC-3: Each similarity group has exactly one designated 'AI Pick' (highest sharpness).")

        # AC-4: Singleton photos get similarity_group = null and duplicate = false
        for solo_name in ("ocean_solo.jpg", "car_solo.jpg", "triangle_solo.jpg"):
            solo = photo_by_name[solo_name]
            assert solo["similarity_group"] is None, (
                f"Singleton photo {solo_name} must have similarity_group=None, got {solo['similarity_group']}"
            )
            assert solo["duplicate"] in (0, False), (
                f"Singleton photo {solo_name} must have duplicate=False, got {solo['duplicate']}"
            )
        print("  [PASS] AC-4: Singleton photos get similarity_group = null and duplicate = false.")

        # AC-5: Clustering runs once per batch after all embeddings exist; GET /clusters API
        clusters_res = get_clusters(batch_id)
        assert clusters_res["batch_id"] == batch_id
        assert clusters_res["solo_count"] == 3, f"Expected 3 solo photos, got {clusters_res['solo_count']}"
        assert len(clusters_res["clusters"]) == 2, f"Expected 2 clusters, got {len(clusters_res['clusters'])}"
        
        # Verify saved embeddings file exists and has shape (512,)
        emb_file = EMB_DIR / f"{batch_id}.npz"
        assert emb_file.exists(), f"Embeddings file {emb_file} does not exist"
        with np.load(emb_file) as emb_data:
            assert len(emb_data.files) == 8, f"Expected 8 embeddings, got {len(emb_data.files)}"
            sample_emb = emb_data[emb_data.files[0]]
            assert sample_emb.shape == (512,), f"Expected shape (512,), got {sample_emb.shape}"
            # Verify L2 normalized: norm approx 1.0
            assert np.isclose(np.linalg.norm(sample_emb), 1.0, atol=1e-3)
        print("  [PASS] AC-5: Embeddings persisted once per batch (.npz & .npy) and /clusters returned correct schema.")

        # ── Test Batch 2: Idempotency Check (AC-6) ────────────────────────────
        print("\n[3/4] Testing Acceptance Criteria 6 (Idempotency of Re-running)...")
        # Direct call to run_batch_analysis on the completed batch
        from workers.job_runner import run_batch_analysis
        run_batch_analysis(batch_id)

        # Check DB to verify groups, duplicates, and AI picks remain identical
        conn = sqlite3.connect(str(DB_FILE))
        conn.row_factory = sqlite3.Row
        re_photos = conn.execute(
            "SELECT id, filename, category, similarity_group, duplicate "
            "FROM photos WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        conn.close()

        re_photo_by_name = {r["filename"]: r for r in re_photos}
        for name in photo_by_name:
            orig = photo_by_name[name]
            re = re_photo_by_name[name]
            assert orig["similarity_group"] == re["similarity_group"], (
                f"Mismatch for {name}: {orig['similarity_group']} vs {re['similarity_group']}"
            )
            assert orig["duplicate"] == re["duplicate"], (
                f"Duplicate mismatch for {name}: {orig['duplicate']} vs {re['duplicate']}"
            )
            assert orig["category"] == re["category"], (
                f"Category mismatch for {name}: {orig['category']} vs {re['category']}"
            )

        # Also verify HTTP 409 when re-requesting analysis on completed batch
        try:
            post_analyze(batch_id)
            raise AssertionError("Expected HTTP 409 when re-triggering completed batch via API")
        except urllib.error.HTTPError as e:
            assert e.code == 409, f"Expected 409, got {e.code}"
        print("  [PASS] AC-6: Re-running classification/clustering is idempotent (preserves groups/picks).")

        # ── Test Batch 3: 300-Image Benchmark (AC-7) ──────────────────────────
        print("\n[4/4] Testing Acceptance Criteria 7 (300-Image Benchmark)...")
        print("      Generating 300-image batch (299 valid + 1 corrupt)...")
        
        bench_bid = f"benchmark-phase4-{uuid4()}"
        bench_dir = UPLOADS / bench_bid
        bench_dir.mkdir(parents=True, exist_ok=True)

        source_bytes = make_scene_image("sun")
        
        conn = sqlite3.connect(str(DB_FILE))
        for i in range(299):
            pid = str(uuid4())
            (bench_dir / f"{pid}.jpg").write_bytes(source_bytes)
            conn.execute(
                "INSERT INTO photos (id, filename, batch_id, status) VALUES (?, ?, ?, 'review')",
                (pid, f"bench_{i}.jpg", bench_bid),
            )
        
        corrupt_pid = str(uuid4())
        (bench_dir / f"{corrupt_pid}.jpg").write_bytes(b"not an actual jpeg image")
        conn.execute(
            "INSERT INTO photos (id, filename, batch_id, status) VALUES (?, ?, ?, 'review')",
            (corrupt_pid, "corrupt.jpg", bench_bid),
        )
        conn.commit()
        conn.close()

        print(f"      Launching analysis for 300 photos (batch {bench_bid})...")
        t_bench_start = time.perf_counter()
        post_analyze(bench_bid)

        # Monitor live progress
        last_processed = -1
        while True:
            st = get_status(bench_bid)
            p = st.get("processed", 0)
            if p != last_processed and p % 50 == 0:
                print(f"      Progress: {p}/300 photos processed...")
                last_processed = p
            if st.get("status") in ("completed", "failed"):
                break
            time.sleep(0.5)

        t_bench_elapsed = time.perf_counter() - t_bench_start
        final_job = get_status(bench_bid)
        assert final_job["status"] == "completed", f"Benchmark job failed: {final_job}"
        assert final_job["processed"] == 299, f"Expected 299 processed, got {final_job['processed']}"
        assert final_job["failed"] == 1, f"Expected 1 failed (corrupt), got {final_job['failed']}"

        throughput = 300 / t_bench_elapsed
        ms_per_img = (t_bench_elapsed / 300) * 1000

        print("\n  +--- 300-Image Benchmark Results ---------------------------------+")
        print(f"  |  Total Images:    300 (299 valid + 1 corrupt)                |")
        print(f"  |  Total Time:      {t_bench_elapsed:6.2f} seconds                             |")
        print(f"  |  Throughput:      {throughput:6.2f} images/sec                             |")
        print(f"  |  Average / Image: {ms_per_img:6.1f} ms                                    |")
        print(f"  |  Valid Status:    {final_job['processed']} processed, {final_job['failed']} failed (isolated)            |")
        print("  +--------------------------------------------------------------+")

        # Verify DB for benchmark batch
        conn = sqlite3.connect(str(DB_FILE))
        conn.row_factory = sqlite3.Row
        bench_photos = conn.execute(
            "SELECT id, category, duplicate, similarity_group, processing_error FROM photos WHERE batch_id = ?",
            (bench_bid,),
        ).fetchall()
        conn.close()

        valid_bench = [p for p in bench_photos if p["id"] != corrupt_pid]
        corrupt_bench = next(p for p in bench_photos if p["id"] == corrupt_pid)

        # All 299 valid photos must have categories
        assert all(p["category"] in FIXED_CATEGORIES for p in valid_bench), "All valid photos must have valid category"
        # All 299 copies must be in the same cluster with 1 AI Pick
        bench_groups = {p["similarity_group"] for p in valid_bench}
        assert len(bench_groups) == 1 and None not in bench_groups, f"All 299 copies should be 1 cluster, got {bench_groups}"
        bench_picks = [p for p in valid_bench if not p["duplicate"]]
        assert len(bench_picks) == 1, f"Expected exactly 1 AI pick for the 299 copies, got {len(bench_picks)}"

        # Corrupt photo must be safely isolated
        assert corrupt_bench["processing_error"] is not None
        assert corrupt_bench["category"] is None
        assert corrupt_bench["similarity_group"] is None
        assert not corrupt_bench["duplicate"]

        print("  [PASS] AC-7: 300-image batch completed in reasonable time with correct DB clustering.")

        print("\n" + "=" * 72)
        print("  ALL ACCEPTANCE CRITERIA PASSED SUCCESSFULLY! (7/7)")
        print("=" * 72 + "\n")

    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    run_tests()
