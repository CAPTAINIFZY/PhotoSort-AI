"""
workers/job_runner.py — Batch analysis worker (Phase 3 + 4).

Two-pass architecture
---------------------
Pass 1 — CV signals (parallel, ProcessPoolExecutor):
  blur, exposure, face detection, eye-state detection.
  Runs in worker sub-processes.  Small models only (OpenCV, MediaPipe).
  Writer thread drains results into SQLite sequentially.

Pass 2 — CLIP embedding + classification (sequential, main thread):
  The large CLIP model (ViT-B-32, ~350 MB) is loaded ONCE in the main
  process rather than once per worker.  PyTorch already uses all CPU
  cores internally via MKL/OpenBLAS, so sequential calls are efficient.
  After all embeddings are collected, cluster_photos() runs and the
  similarity/duplicate fields are written.

WAL mode (set in init_db) keeps /status reads non-blocking during
either pass.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from db import DB_PATH, update_photo_analysis, upsert_job, record_batch_error

_MAX_WORKERS = min(os.cpu_count() or 1, 4)


# ── Pass-1 worker (runs in child processes — CV signals only) ─────────────────

def _analyse_cv_one(args: tuple[str, str]) -> dict:
    """Picklable top-level function for ProcessPoolExecutor."""
    photo_id, image_path = args
    try:
        import sys as _sys
        _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _backend_dir not in _sys.path:
            _sys.path.insert(0, _backend_dir)

        from ai.pipeline import analyze_cv_signals
        return analyze_cv_signals(photo_id, image_path)
    except Exception:
        return {
            "photo_id":         photo_id,
            "processing_error": f"worker crash: {traceback.format_exc(limit=2).strip()}",
            "sharpness_score":  None,
        }


# ── Writer thread ─────────────────────────────────────────────────────────────

class _WriterThread(threading.Thread):
    SENTINEL = None

    def __init__(self, q: queue.Queue):
        super().__init__(daemon=True)
        self._q = q

    def run(self):
        while True:
            item = self._q.get()
            if item is self.SENTINEL:
                break
            try:
                update_photo_analysis(item["photo_id"], item)
            except Exception:
                pass
            finally:
                self._q.task_done()


# ── Embedding persistence ─────────────────────────────────────────────────────

def _embeddings_dir() -> Path:
    project_root = Path(DB_PATH).parent
    emb_dir = Path(os.getenv(
        "EMBEDDINGS_DIR",
        str(project_root / "processed" / "embeddings"),
    ))
    emb_dir.mkdir(parents=True, exist_ok=True)
    return emb_dir


def _embeddings_exist(batch_id: str) -> bool:
    emb_dir = _embeddings_dir()
    return (emb_dir / f"{batch_id}.npy").exists() or (emb_dir / f"{batch_id}.npz").exists()


def _embeddings_path(batch_id: str) -> Path:
    return _embeddings_dir() / f"{batch_id}.npz"


def _save_embeddings(batch_id: str, embeddings: dict) -> None:
    import numpy as np
    emb_dir = _embeddings_dir()
    npz_path = emb_dir / f"{batch_id}.npz"
    np.savez(npz_path, **embeddings)
    npy_path = emb_dir / f"{batch_id}.npy"
    np.save(npy_path, embeddings, allow_pickle=True)


def _load_embeddings(batch_id: str) -> dict | None:
    import numpy as np
    emb_dir = _embeddings_dir()
    npz_path = emb_dir / f"{batch_id}.npz"
    npy_path = emb_dir / f"{batch_id}.npy"
    if npz_path.exists():
        with np.load(npz_path) as data:
            return {k: data[k] for k in data.files}
    if npy_path.exists():
        loaded = np.load(npy_path, allow_pickle=True)
        if isinstance(loaded, dict):
            return loaded
        if hasattr(loaded, "item"):
            return loaded.item()
    return None


# ── Cluster DB write ──────────────────────────────────────────────────────────

def _write_cluster_results(
    batch_id: str,
    clusters: dict[str, int],
    representatives: dict[int, str],
) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute(
            "UPDATE photos SET similarity_group = NULL, duplicate = 0 WHERE batch_id = ?",
            (batch_id,),
        )
        for pid, cid in clusters.items():
            is_rep = representatives.get(cid) == pid
            conn.execute(
                "UPDATE photos SET similarity_group = ?, duplicate = ? WHERE id = ?",
                (cid, 0 if is_rep else 1, pid),
            )
        conn.commit()
    finally:
        conn.close()


def _write_categories(results: list[dict]) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        for r in results:
            cat = r.get("category")
            if cat is not None:
                conn.execute(
                    "UPDATE photos SET category = ? WHERE id = ?",
                    (cat, r["photo_id"]),
                )
        conn.commit()
    finally:
        conn.close()


def score_batch(batch_id: str, id_to_path: Optional[dict[str, str]] = None) -> dict[str, dict]:
    """
    Pass 3: Composition, Scoring & Recommendation Engine (Phase 5).
    Evaluates composition, calculates composite scores using dynamic weights,
    re-evaluates cluster AI picks using final composite scores, and generates
    reasons and recommendations (keep/review/reject).
    """
    import json
    from collections import Counter
    from ai.composition import calculate_composition
    from ai.scoring import (
        calculate_face_score,
        calculate_uniqueness_score,
        calculate_final_score,
        generate_recommendation,
        normalize_sharpness,
        normalize_exposure,
        get_recommendation_thresholds,
    )
    from ai.similarity import pick_cluster_representative
    from config import get_weights

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    photo_rows = conn.execute(
        """SELECT id, filename, sharpness_score, mean_brightness,
                  clipped_shadows_pct, clipped_highlights_pct,
                  face_count, face_bboxes, closed_eyes_detected,
                  possible_closed_eyes_count, duplicate, similarity_group,
                  processing_error, composition_score
           FROM photos WHERE batch_id = ?""",
        (batch_id,),
    ).fetchall()
    conn.close()

    if not photo_rows:
        return {}

    if id_to_path is None:
        project_root = Path(DB_PATH).parent
        upload_dir = Path(os.getenv("UPLOAD_DIR", str(project_root / "uploads" / "originals")))
        id_to_path = {}
        for r in photo_rows:
            ext = os.path.splitext(r["filename"])[1].lower()
            id_to_path[r["id"]] = str(upload_dir / batch_id / f"{r['id']}{ext}")

    cluster_counts = Counter(
        r["similarity_group"] for r in photo_rows if r["similarity_group"] is not None
    )

    weights = get_weights()
    thresholds = get_recommendation_thresholds(weights)

    scores_by_id: dict[str, float] = {}
    scored_photos: dict[str, dict] = {}

    for row in photo_rows:
        pid = row["id"]
        img_path = id_to_path.get(pid)

        try:
            # Error isolation for corrupt images
            if row["processing_error"] and row["sharpness_score"] is None:
                scored_photos[pid] = {
                    "score": 0.0,
                    "composition_score": 0.0,
                    "face_score": 0.0,
                    "uniqueness_score": 0.0,
                    "exposure_score": 0.0,
                    "recommendation": "reject",
                    "reasons": ["Unreadable or corrupted image file"],
                    "status": "error",
                }
                scores_by_id[pid] = 0.0
                continue

            face_bboxes = []
            if row["face_bboxes"]:
                try:
                    face_bboxes = json.loads(row["face_bboxes"])
                except Exception:
                    face_bboxes = []

            # 1. Composition score
            if img_path and os.path.exists(img_path):
                comp_res = calculate_composition(img_path, face_bboxes)
                comp_score = comp_res["composition_score"]
                comp_issues = comp_res["issues"]
            elif row["composition_score"] is not None:
                comp_score = float(row["composition_score"])
                comp_issues = []
            else:
                comp_score = 50.0
                comp_issues = []

            # 2. Face score
            face_cnt = row["face_count"] or 0
            closed_cnt = row["possible_closed_eyes_count"] or 0
            f_score = calculate_face_score(face_cnt, face_bboxes, closed_cnt)

            # 3. Uniqueness score (for cluster members, evaluate raw baseline first)
            sg = row["similarity_group"]
            c_size = cluster_counts.get(sg, 0)
            is_singleton = (sg is None or c_size <= 1)
            base_uniq = 100.0 if is_singleton else calculate_uniqueness_score(sg, c_size, False)

            # 4. Exposure score
            exp_data = {
                "mean_brightness": row["mean_brightness"],
                "clipped_shadows_pct": row["clipped_shadows_pct"],
                "clipped_highlights_pct": row["clipped_highlights_pct"],
            }
            exp_score = normalize_exposure(exp_data)

            # 5. Composite score (for cluster members, evaluate raw quality without duplicate penalty)
            fin_score = calculate_final_score(
                sharpness=row["sharpness_score"],
                exposure_data=exp_data,
                face_score=f_score,
                composition_score=comp_score,
                uniqueness_score=base_uniq,
                duplicate=False,
                weights=weights,
                closed_eyes_count=closed_cnt,
                face_count=face_cnt,
            )
            scores_by_id[pid] = fin_score

            rec_details = {
                "norm_sharpness": normalize_sharpness(row["sharpness_score"]),
                "norm_exposure": exp_score,
                "face_score": f_score,
                "composition_score": comp_score,
                "face_count": face_cnt,
                "closed_eyes_count": closed_cnt,
                "composition_issues": comp_issues,
            }
            rec, reasons = generate_recommendation(
                score=fin_score,
                duplicate=False,
                is_ai_pick=is_singleton,
                details=rec_details,
                thresholds=thresholds,
            )

            scored_photos[pid] = {
                "score": fin_score,
                "composition_score": comp_score,
                "face_score": f_score,
                "uniqueness_score": base_uniq,
                "exposure_score": exp_score,
                "recommendation": rec,
                "reasons": reasons,
                "status": rec,
                "duplicate": 0,
                "rec_details": rec_details,
                "exp_data": exp_data,
                "closed_cnt": closed_cnt,
                "face_cnt": face_cnt,
                "sharpness": row["sharpness_score"],
            }
        except Exception as exc:
            scored_photos[pid] = {
                "score": 0.0,
                "composition_score": 0.0,
                "face_score": 0.0,
                "uniqueness_score": 0.0,
                "exposure_score": 0.0,
                "recommendation": "reject",
                "reasons": [f"Scoring evaluation error: {exc}"],
                "status": "error",
            }
            scores_by_id[pid] = 0.0
            record_batch_error(
                batch_id=batch_id,
                photo_id=pid,
                filename=row["filename"],
                stage="scoring",
                reason=str(exc),
            )

    # ── Re-evaluate AI Pick per cluster based on FINAL COMPOSITE SCORE ─────
    cid_to_members: dict[int, list[str]] = defaultdict(list)
    for row in photo_rows:
        sg = row["similarity_group"]
        if sg is not None:
            cid_to_members[sg].append(row["id"])

    for cid, pids in cid_to_members.items():
        best_pid = pick_cluster_representative(pids, scores_by_id)
        c_size = len(pids)
        for pid in pids:
            if pid not in scored_photos or scored_photos[pid]["status"] == "error":
                continue

            is_pick = (pid == best_pid)
            scored_photos[pid]["duplicate"] = 0 if is_pick else 1

            new_uniq = calculate_uniqueness_score(cid, c_size, is_pick)
            scored_photos[pid]["uniqueness_score"] = new_uniq

            # Winner has duplicate=False; non-picks have duplicate=True (penalty deducted)
            new_final = calculate_final_score(
                sharpness=scored_photos[pid]["sharpness"],
                exposure_data=scored_photos[pid]["exp_data"],
                face_score=scored_photos[pid]["face_score"],
                composition_score=scored_photos[pid]["composition_score"],
                uniqueness_score=new_uniq,
                duplicate=not is_pick,
                weights=weights,
                closed_eyes_count=scored_photos[pid]["closed_cnt"],
                face_count=scored_photos[pid]["face_cnt"],
            )
            scored_photos[pid]["score"] = new_final
            scores_by_id[pid] = new_final

            new_rec, new_reasons = generate_recommendation(
                score=new_final,
                duplicate=not is_pick,
                is_ai_pick=is_pick,
                details=scored_photos[pid].get("rec_details", {}),
                thresholds=thresholds,
            )
            scored_photos[pid]["recommendation"] = new_rec
            scored_photos[pid]["reasons"] = new_reasons
            scored_photos[pid]["status"] = new_rec

    # Persist all scoring results to database
    for pid, data in scored_photos.items():
        clean_data = {
            k: v for k, v in data.items()
            if k not in ("rec_details", "exp_data", "closed_cnt", "face_cnt", "sharpness")
        }
        update_photo_analysis(pid, clean_data)

    return scored_photos


def rescore_batch(batch_id: str) -> dict[str, dict]:
    """Re-score a batch using current weights from scoring_weights.json."""
    return score_batch(batch_id)


# ── Public entry point ────────────────────────────────────────────────────────

def run_batch_analysis(batch_id: str) -> None:
    """
    Full Phase 3 + 4 pipeline for a batch.

    Steps
    -----
    1.  Fetch photo rows.
    2.  Set jobs.status = 'running'.
    3.  Pass 1: ProcessPoolExecutor → CV signals (blur/exposure/faces/eyes).
        Writer thread persists results; processed/failed counts updated live.
    4.  Pass 2: sequential CLIP embedding + classification in main thread.
        Progress counter not updated per-photo (CLIP runs after pool).
    5.  Save embeddings .npz (skip if already saved — idempotent).
    6.  Cluster photos (union-find on cosine-sim matrix).
    7.  Write similarity_group / duplicate / category to DB.
    8.  Set jobs.status = 'completed'.
    """
    import numpy as np

    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. Fetch photos ───────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    photos = conn.execute(
        "SELECT id, filename FROM photos WHERE batch_id = ?",
        (batch_id,),
    ).fetchall()
    conn.close()

    total = len(photos)
    if total == 0:
        upsert_job(batch_id, status="completed", total=0,
                   processed=0, failed=0, finished_at=now_iso)
        return

    # ── 2. Mark running ───────────────────────────────────────────────────────
    upsert_job(batch_id, status="running", total=total,
               processed=0, failed=0, started_at=now_iso)

    # ── Build work list ───────────────────────────────────────────────────────
    project_root = Path(DB_PATH).parent
    upload_dir = Path(os.getenv(
        "UPLOAD_DIR", str(project_root / "uploads" / "originals")
    ))

    def _orig_path(row) -> str:
        ext = os.path.splitext(row["filename"])[1].lower()
        return str(upload_dir / batch_id / f"{row['id']}{ext}")

    work_items    = [(row["id"], _orig_path(row)) for row in photos]
    id_to_path    = {pid: path for pid, path in work_items}

    # ── 3. Pass 1: CV signals via ProcessPoolExecutor ─────────────────────────
    write_q: queue.Queue = queue.Queue()
    writer = _WriterThread(write_q)
    writer.start()

    processed = 0
    failed    = 0
    cv_results: list[dict] = []

    import multiprocessing
    mp_ctx = multiprocessing.get_context("spawn")

    try:
        with ProcessPoolExecutor(max_workers=_MAX_WORKERS, mp_context=mp_ctx) as pool:
            futures = {pool.submit(_analyse_cv_one, item): item[0]
                       for item in work_items}

            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    pid = futures[future]
                    result = {
                        "photo_id":         pid,
                        "processing_error": f"future error: {exc}",
                        "sharpness_score":  None,
                    }

                # Write all signals including face_bboxes (now stored as JSON)
                db_result = dict(result)
                write_q.put(db_result)
                cv_results.append(result)

                is_failure = (
                    result.get("processing_error")
                    and result.get("sharpness_score") is None
                )
                if is_failure:
                    failed += 1
                    pid = result.get("photo_id")
                    fname = next((p["filename"] for p in photos if p["id"] == pid), "unknown")
                    record_batch_error(
                        batch_id=batch_id,
                        photo_id=pid,
                        filename=fname,
                        stage="cv_analysis",
                        reason=result.get("processing_error") or "cv_analysis_failed",
                    )
                else:
                    processed += 1

                upsert_job(batch_id, processed=processed, failed=failed)

    except Exception:
        upsert_job(batch_id, status="failed", processed=processed,
                   failed=failed,
                   finished_at=datetime.now(timezone.utc).isoformat())
        return
    finally:
        write_q.put(_WriterThread.SENTINEL)
        writer.join(timeout=30)

    # ── 4. Pass 2: CLIP embeddings (sequential, main thread) ─────────────────
    # Check for pre-saved embeddings (idempotent re-run support)
    if _embeddings_exist(batch_id):
        embeddings = _load_embeddings(batch_id) or {}
        from ai.classify import classify_photo
        cat_results = []
        for pid, _ in work_items:
            emb = embeddings.get(pid)
            if emb is not None:
                cat_results.append({"photo_id": pid, "category": classify_photo(emb)})
        if cat_results:
            _write_categories(cat_results)
    else:
        # Load CLIP once in main process, run sequentially
        emb_results = []
        try:
            from ai.pipeline import analyze_embedding

            for pid, image_path in work_items:
                try:
                    emb_result = analyze_embedding(pid, image_path)
                except Exception:
                    emb_result = {"photo_id": pid, "embedding": None, "category": None}
                emb_results.append(emb_result)

        except Exception:
            # CLIP unavailable — proceed without embeddings/categories
            emb_results = [
                {"photo_id": pid, "embedding": None, "category": None}
                for pid, _ in work_items
            ]

        # Persist categories to DB
        _write_categories(emb_results)

        # ── 5. Save embeddings ─────────────────────────────────────────────────
        embeddings: dict[str, np.ndarray] = {
            r["photo_id"]: r["embedding"]
            for r in emb_results
            if r.get("embedding") is not None
        }
        if embeddings:
            _save_embeddings(batch_id, embeddings)

    # ── 6. Cluster photos (Phase 4 preliminary clustering) ────────────────────
    try:
        from ai.similarity import cluster_photos, pick_cluster_representative

        clusters = cluster_photos(embeddings)

        sharpness: dict[str, float] = {
            r["photo_id"]: (r.get("sharpness_score") or 0.0)
            for r in cv_results
        }

        cid_to_pids: dict[int, list[str]] = defaultdict(list)
        for pid, cid in clusters.items():
            cid_to_pids[cid].append(pid)

        representatives: dict[int, str] = {
            cid: pick_cluster_representative(pids, sharpness)
            for cid, pids in cid_to_pids.items()
        }

        # ── 7. Write preliminary cluster results ──────────────────────────────
        _write_cluster_results(batch_id, clusters, representatives)

    except Exception:
        pass   # clustering failure is non-fatal; photos are still analysed

    # ── 8. Pass 3: Composition, Scoring & Recommendation (Phase 5) ────────────
    try:
        score_batch(batch_id, id_to_path)
    except Exception:
        pass   # scoring pass failure is isolated


    # ── 9. Mark completed (only after scoring pass completes) ─────────────────
    finish_iso   = datetime.now(timezone.utc).isoformat()
    final_status = "completed" if failed < total else "failed"
    upsert_job(batch_id, status=final_status,
               processed=processed, failed=failed, finished_at=finish_iso)
