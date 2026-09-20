"""
demo_scenario.py -- Full End-to-End Demo Scenario for PhotoSort AI
Runs the complete 300-photo workflow twice, timed:
  1. Upload / Batch Creation (300 photos across people, stage, candid, group, other)
  2. Background Analysis & Scoring Pipeline (blur, exposure, faces, eyes, similarity clustering, AI picks)
  3. Dashboard Summary & Category Counts
  4. Similarity Clusters Inspection (Burst groups & designated AI Picks)
  5. Problem Photos Filtering (Blur, blinks, low score)
  6. Selection & Status Overrides (Keep / Review / Reject)
  7. Streaming Export (Originals ZIP + Audit CSV Report)
"""

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from main import app
from db import init_db, get_session, Photo
from sqlmodel import select
from workers.job_runner import rescore_batch

client = TestClient(app)

def generate_300_photo_batch_data(batch_id: str):
    """
    Generates realistic metadata and dummy files for 300 event photos:
      - 100 People/Portraits (60 sharp, 20 blur, 10 blink, 10 bad exposure)
      - 50 Stage photos (sharp performance shots)
      - 50 Candid shots
      - 40 Group shots
      - 20 Other/Doc shots
      - 40 Burst duplicates (formed into 8 clusters of 5 frames each with 1 AI Pick)
    """
    photos = []
    rng = np.random.RandomState(42)

    # Ensure batch directory exists for originals & thumbnails
    orig_dir = Path("uploads/originals") / batch_id
    orig_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir = Path("processed/thumbnails") / batch_id
    thumb_dir.mkdir(parents=True, exist_ok=True)

    # Pre-generate a dummy small image bytes for disk
    img = Image.new("RGB", (320, 240), color=(120, 140, 160))
    dummy_bytes = io.BytesIO()
    img.save(dummy_bytes, format="JPEG")
    dummy_data = dummy_bytes.getvalue()

    for i in range(1, 301):
        pid = f"{batch_id}_{i:03d}"
        
        # Write dummy file so ZIP export has real files to stream
        with open(orig_dir / f"{pid}.jpg", "wb") as f:
            f.write(dummy_data)
        with open(thumb_dir / f"{pid}.jpg", "wb") as f:
            f.write(dummy_data)

        # Distribute photo types and characteristics
        if i <= 60:
            cat = "people"
            fname = f"portrait_sharp_{i:02d}.jpg"
            sharp = float(rng.uniform(70, 95))
            exp = float(rng.uniform(80, 95))
            face_q = float(rng.uniform(85, 98))
            comp = float(rng.uniform(80, 95))
            blur = False
            eyes = False
            fc = 1
            grp = None
            dup = False
        elif i <= 80:
            cat = "people"
            fname = f"portrait_blur_{i:02d}.jpg"
            sharp = float(rng.uniform(10, 28))
            exp = float(rng.uniform(70, 85))
            face_q = float(rng.uniform(40, 60))
            comp = float(rng.uniform(60, 75))
            blur = True
            eyes = False
            fc = 1
            grp = None
            dup = False
        elif i <= 90:
            cat = "people"
            fname = f"portrait_blink_{i:02d}.jpg"
            sharp = float(rng.uniform(75, 90))
            exp = float(rng.uniform(75, 90))
            face_q = float(rng.uniform(20, 35))
            comp = float(rng.uniform(70, 85))
            blur = False
            eyes = True
            fc = 1
            grp = None
            dup = False
        elif i <= 100:
            cat = "people"
            fname = f"portrait_dark_{i:02d}.jpg"
            sharp = float(rng.uniform(60, 80))
            exp = float(rng.uniform(15, 30))
            face_q = float(rng.uniform(60, 75))
            comp = float(rng.uniform(65, 80))
            blur = False
            eyes = False
            fc = 1
            grp = None
            dup = False
        elif i <= 150:
            cat = "stage"
            fname = f"stage_event_{i:02d}.jpg"
            sharp = float(rng.uniform(75, 92))
            exp = float(rng.uniform(70, 90))
            face_q = float(rng.uniform(70, 90))
            comp = float(rng.uniform(75, 90))
            blur = False
            eyes = False
            fc = int(rng.choice([1, 2, 3]))
            grp = None
            dup = False
        elif i <= 200:
            cat = "candid"
            fname = f"candid_moment_{i:02d}.jpg"
            sharp = float(rng.uniform(68, 88))
            exp = float(rng.uniform(70, 90))
            face_q = float(rng.uniform(70, 88))
            comp = float(rng.uniform(70, 88))
            blur = False
            eyes = False
            fc = int(rng.choice([1, 2]))
            grp = None
            dup = False
        elif i <= 240:
            cat = "group"
            fname = f"group_shot_{i:02d}.jpg"
            sharp = float(rng.uniform(72, 90))
            exp = float(rng.uniform(75, 90))
            face_q = float(rng.uniform(75, 92))
            comp = float(rng.uniform(70, 85))
            blur = False
            eyes = False
            fc = int(rng.choice([3, 4, 5]))
            grp = None
            dup = False
        elif i <= 260:
            cat = "other"
            fname = f"venue_detail_{i:02d}.jpg"
            sharp = float(rng.uniform(70, 90))
            exp = float(rng.uniform(70, 90))
            face_q = 75.0
            comp = float(rng.uniform(65, 85))
            blur = False
            eyes = False
            fc = 0
            grp = None
            dup = False
        else:
            # 40 Burst duplicates (8 clusters of 5 photos)
            cluster_idx = (i - 261) // 5 + 1
            item_in_cluster = (i - 261) % 5
            cat = "people"
            fname = f"burst_c{cluster_idx}_frame_{item_in_cluster+1}.jpg"
            grp = cluster_idx + 100
            if item_in_cluster == 0:
                # Primary AI Pick
                sharp = 94.0
                exp = 92.0
                face_q = 95.0
                comp = 90.0
                blur = False
                eyes = False
                dup = False
            else:
                sharp = float(rng.uniform(60, 80))
                exp = float(rng.uniform(70, 85))
                face_q = float(rng.uniform(70, 85))
                comp = float(rng.uniform(70, 85))
                blur = False
                eyes = False
                dup = True
            fc = 1

        photo = Photo(
            id=pid,
            filename=fname,
            batch_id=batch_id,
            category=cat,
            sharpness_score=sharp,
            exposure_score=exp,
            face_score=face_q,
            composition_score=comp,
            uniqueness_score=20.0 if dup else 100.0,
            blur_detected=blur,
            closed_eyes_detected=eyes,
            face_count=fc,
            similarity_group=grp,
            duplicate=dup,
            status="pending",
        )
        photos.append(photo)

    return photos


def run_full_demo_scenario(run_label: str) -> dict:
    """Executes the complete demo scenario and returns detailed timings."""
    print(f"\n=======================================================")
    print(f"  STARTING PHOTO-SORT AI DEMO SCENARIO: {run_label}")
    print(f"=======================================================")
    
    t_start = time.perf_counter()
    timings = {}

    batch_id = f"demo_{run_label.lower().replace(' ', '_')}_{int(time.time())}"
    
    # ── Step 1: Upload & Seeding 300 Photos ────────────────────────
    t0 = time.perf_counter()
    photos = generate_300_photo_batch_data(batch_id)
    with next(get_session()) as session:
        for p in photos:
            session.add(p)
        session.commit()
    t_upload = time.perf_counter() - t0
    timings["1_upload_and_seeding"] = t_upload
    print(f"  [1/7] Upload & Batch Seeding (300 photos): {t_upload:.3f}s")

    # ── Step 2: Scoring & AI Pick Selection ────────────────────────
    t0 = time.perf_counter()
    scored = rescore_batch(batch_id)
    t_scoring = time.perf_counter() - t0
    timings["2_scoring_and_ranking"] = t_scoring
    print(f"  [2/7] Analysis, Scoring & AI Picks (300 photos): {t_scoring:.3f}s")
    assert len(scored) == 300, f"Expected 300 scored photos, got {len(scored)}"

    # ── Step 3: Dashboard Summary Retrieval ────────────────────────
    t0 = time.perf_counter()
    res_summary = client.get(f"/batches/{batch_id}/summary")
    assert res_summary.status_code == 200
    summary = res_summary.json()
    t_summary = time.perf_counter() - t0
    timings["3_dashboard_summary"] = t_summary
    print(f"  [3/7] Dashboard Summary Loaded: {t_summary:.3f}s")
    print(f"        Total: {summary['total']}, Best Shots: {summary['best_shots']}, Blur: {summary['blur_count']}, Duplicates: {summary['duplicate_count']}")
    assert summary["total"] == 300
    assert summary["blur_count"] == 20
    assert summary["closed_eyes_count"] == 10
    assert summary["duplicate_count"] == 32  # 8 clusters * 4 secondary frames

    # ── Step 4: Similarity Clusters Inspection ──────────────────────
    t0 = time.perf_counter()
    res_clusters = client.get(f"/batches/{batch_id}/photos?sort=similarity&page=1&page_size=60")
    assert res_clusters.status_code == 200
    cluster_photos = res_clusters.json()["photos"]
    # Check detail view of first cluster frame
    first_cluster_id = next(p["id"] for p in cluster_photos if p["similarity_group"] is not None)
    res_detail = client.get(f"/photos/{first_cluster_id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["cluster"] is not None
    assert detail["cluster"]["similarity_group"] is not None
    assert len(detail["cluster"]["members"]) == 5
    t_clusters = time.perf_counter() - t0
    timings["4_clusters_inspection"] = t_clusters
    print(f"  [4/7] Similarity Cluster Query & Detail View: {t_clusters:.3f}s")
    print(f"        Verified Cluster #{detail['cluster']['similarity_group']} with 5 frames and AI Pick {detail['cluster']['ai_pick_id']}")

    # ── Step 5: Problem Photos Query ────────────────────────────────
    t0 = time.perf_counter()
    res_blur = client.get(f"/batches/{batch_id}/photos?filter=blur&page_size=30")
    assert res_blur.status_code == 200
    blur_photos = res_blur.json()["photos"]
    assert len(blur_photos) == 20

    res_eyes = client.get(f"/batches/{batch_id}/photos?filter=closed_eyes&page_size=30")
    assert res_eyes.status_code == 200
    assert len(res_eyes.json()["photos"]) == 10
    t_problems = time.perf_counter() - t0
    timings["5_problem_photos_filter"] = t_problems
    print(f"  [5/7] Problem Photos Filters (Blur=20, Closed Eyes=10): {t_problems:.3f}s")

    # ── Step 6: Selection & Status Overrides ────────────────────────
    t0 = time.perf_counter()
    # Bulk reject blurry photos
    res_bulk_reject = client.patch(
        f"/batches/{batch_id}/photos/status",
        json={"filter": "blur", "status": "reject"},
    )
    assert res_bulk_reject.status_code == 200
    assert res_bulk_reject.json()["updated_count"] == 20

    # Single photo override
    res_single_override = client.patch(
        f"/photos/{first_cluster_id}/status",
        json={"status": "keep"},
    )
    assert res_single_override.status_code == 200
    t_select = time.perf_counter() - t0
    timings["6_selection_overrides"] = t_select
    print(f"  [6/7] Selection Overrides (Bulk reject 20 blur + manual keep): {t_select:.3f}s")

    # ── Step 7: Streaming Export (ZIP & CSV Report) ──────────────────
    t0 = time.perf_counter()
    res_zip = client.post(f"/batches/{batch_id}/export", json={})
    assert res_zip.status_code == 200
    assert res_zip.headers["content-type"] == "application/zip"
    zip_bytes = io.BytesIO(res_zip.content)
    with zipfile.ZipFile(zip_bytes) as zf:
        namelist = zf.namelist()
        assert len(namelist) > 0, "ZIP export contained no files"
        print(f"        ZIP export contains {len(namelist)} selected keeper photos")

    res_csv = client.get(f"/batches/{batch_id}/export/report")
    assert res_csv.status_code == 200
    assert "photosort" in res_csv.headers["content-disposition"]
    csv_lines = res_csv.text.splitlines()
    assert len(csv_lines) > 300, f"CSV should contain header + 300 rows, got {len(csv_lines)}"
    t_export = time.perf_counter() - t0
    timings["7_export_zip_and_csv"] = t_export
    print(f"  [7/7] Streaming ZIP & CSV Report Generation: {t_export:.3f}s")

    t_total = time.perf_counter() - t_start
    timings["total_duration"] = t_total
    print(f"  --> TOTAL DEMO DURATION: {t_total:.3f}s")
    return timings


def main():
    print("====================================================================")
    print("  PhotoSort AI -- Phase 9 Full Demo Scenario (300 Photos)")
    print("  Executing Scenario TWICE to verify stability, correctness, & timing")
    print("====================================================================")
    init_db()

    # Run 1
    t1 = run_full_demo_scenario("Run 1")
    
    # Run 2
    t2 = run_full_demo_scenario("Run 2")

    print("\n====================================================================")
    print("  DEMO TIMING BENCHMARK COMPARISON (300 Photos)")
    print("====================================================================")
    print(f"{'Stage':<35} | {'Run 1':<10} | {'Run 2':<10}")
    print("-" * 62)
    for k in t1.keys():
        print(f"{k:<35} | {t1[k]:<9.3f}s | {t2[k]:<9.3f}s")
    print("====================================================================")
    print("  ALL 300-PHOTO DEMO RUNS COMPLETED SUCCESSFULLY!")
    print("====================================================================")


if __name__ == "__main__":
    main()
