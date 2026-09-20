"""
routers/batches.py — Batch summary, gallery, bulk status override, and export endpoints.

Endpoints:
    GET   /batches/{batch_id}/summary       — Aggregated statistics for dashboard summary strip.
    GET   /batches/{batch_id}/photos        — Filtered, sorted, paginated photo list for gallery.
    PATCH /batches/{batch_id}/photos/status — Bulk update workflow status for photos in batch.
    POST  /batches/{batch_id}/export        — Stream ZIP file of selected photos.
    GET   /batches/{batch_id}/export/report — Download CSV report matching dashboard statistics.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Optional
import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from ai.scoring import get_recommendation_thresholds
from db import DB_PATH

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(_PROJECT_ROOT / "uploads/originals")))

router = APIRouter(tags=["Batches"])


# ── Response & Request Models ─────────────────────────────────────────────────

class CategoryBreakdown(BaseModel):
    people: int = 0
    stage: int = 0
    candid: int = 0
    group: int = 0
    other: int = 0


class BatchSummaryResponse(BaseModel):
    total: int
    best_shots: int
    selected_count: int = 0
    categories: CategoryBreakdown
    blur_count: int
    duplicate_count: int
    closed_eyes_count: int
    low_score_count: int
    failed_count: int = 0


class BatchErrorItem(BaseModel):
    photo_id: Optional[str] = None
    filename: str
    stage: str
    reason: str


class BatchPhotoItem(BaseModel):
    id: str
    filename: str
    thumbnail_url: str
    category: Optional[str] = None
    score: Optional[float] = None
    blur_detected: Optional[bool] = None
    closed_eyes_detected: Optional[bool] = None
    duplicate: Optional[bool] = None
    similarity_group: Optional[int] = None
    recommendation: Optional[str] = None
    status: Optional[str] = None


class PaginatedPhotosResponse(BaseModel):
    photos: list[BatchPhotoItem]
    total: int
    page: int
    page_size: int


class BulkStatusUpdateRequest(BaseModel):
    photo_ids: Optional[list[str]] = None
    status: str
    filter: Optional[str] = None
    category: Optional[str] = None


class BulkStatusUpdateResponse(BaseModel):
    updated_count: int


class ExportBatchRequest(BaseModel):
    photo_ids: Optional[list[str]] = None


# ── 1. GET /batches/{batch_id}/summary ────────────────────────────────────────

@router.get(
    "/batches/{batch_id}/summary",
    response_model=BatchSummaryResponse,
)
def get_batch_summary(batch_id: str) -> BatchSummaryResponse:
    """
    Return aggregated counts for batch summary strip and category tiles.

    Thresholds are retrieved dynamically from scoring configuration.
    Raises 404 if the batch has no photos.
    """
    thresholds = get_recommendation_thresholds()
    review_threshold = thresholds.get("review", 50.0)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # Aggregated stats query
        row = conn.execute(
            """
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN recommendation = 'keep' THEN 1 ELSE 0 END) AS best_shots,
                SUM(CASE WHEN lower(status) = 'keep' THEN 1 ELSE 0 END) AS selected_count,
                SUM(CASE WHEN blur_detected = 1 THEN 1 ELSE 0 END) AS blur_count,
                SUM(CASE WHEN duplicate = 1 THEN 1 ELSE 0 END) AS duplicate_count,
                SUM(CASE WHEN closed_eyes_detected = 1 THEN 1 ELSE 0 END) AS closed_eyes_count,
                SUM(CASE WHEN score IS NOT NULL AND score < ? THEN 1 ELSE 0 END) AS low_score_count,
                SUM(CASE WHEN lower(status) = 'error' OR (processing_error IS NOT NULL AND sharpness_score IS NULL) THEN 1 ELSE 0 END) AS failed_count
            FROM photos
            WHERE batch_id = ?
            """,
            (review_threshold, batch_id),
        ).fetchone()

        if not row or row["total"] == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No photos found for batch '{batch_id}'.",
            )

        # Check for any upload errors in batch_errors that didn't make it to photos table
        upload_errs = conn.execute(
            "SELECT COUNT(*) FROM batch_errors WHERE batch_id = ? AND stage = 'upload'",
            (batch_id,),
        ).fetchone()[0]

        total_failed = (row["failed_count"] or 0) + (upload_errs or 0)

        # Categories breakdown query
        cat_rows = conn.execute(
            """
            SELECT category, COUNT(*) as cnt
            FROM photos
            WHERE batch_id = ? AND category IS NOT NULL
            GROUP BY category
            """,
            (batch_id,),
        ).fetchall()

        # Fixed categories mapping
        categories = {
            "people": 0,
            "stage": 0,
            "candid": 0,
            "group": 0,
            "other": 0,
        }
        other_count = 0
        for cat_row in cat_rows:
            cat = (cat_row["category"] or "").lower()
            cnt = cat_row["cnt"]
            if cat in categories and cat != "other":
                categories[cat] = cnt
            else:
                other_count += cnt
        categories["other"] = other_count

        return BatchSummaryResponse(
            total=row["total"] or 0,
            best_shots=row["best_shots"] or 0,
            selected_count=row["selected_count"] or 0,
            categories=CategoryBreakdown(**categories),
            blur_count=row["blur_count"] or 0,
            duplicate_count=row["duplicate_count"] or 0,
            closed_eyes_count=row["closed_eyes_count"] or 0,
            low_score_count=row["low_score_count"] or 0,
            failed_count=total_failed,
        )
    finally:
        conn.close()


# ── 2. GET /batches/{batch_id}/photos ─────────────────────────────────────────

def build_photos_query(
    batch_id: str,
    category: Optional[str] = None,
    status: Optional[str] = None,
    filter: Optional[str] = None,
    sort: Optional[str] = "score_desc",
) -> tuple[str, list[Any], str]:
    """
    Build where clauses, query parameters, and order clause for photos queries.
    Shared by GET /batches/{batch_id}/photos and GET /photos/{photo_id}/adjacent.
    """
    where_clauses = ["batch_id = ?"]
    params: list[Any] = [batch_id]

    if category:
        cat_lower = category.lower().strip()
        if cat_lower == "other":
            where_clauses.append("(category IS NULL OR lower(category) NOT IN ('people', 'stage', 'candid', 'group'))")
        else:
            where_clauses.append("lower(category) = ?")
            params.append(cat_lower)

    if status:
        where_clauses.append("lower(status) = ?")
        params.append(status.lower().strip())

    if filter:
        f = filter.lower().strip()
        if f == "best_shots":
            where_clauses.append("recommendation = 'keep'")
        elif f == "blur":
            where_clauses.append("blur_detected = 1")
        elif f == "duplicates":
            where_clauses.append("duplicate = 1")
        elif f == "closed_eyes":
            where_clauses.append("closed_eyes_detected = 1")
        elif f == "low_score":
            thresholds = get_recommendation_thresholds()
            review_th = thresholds.get("review", 50.0)
            where_clauses.append("(score IS NOT NULL AND score < ?)")
            params.append(review_th)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filter '{filter}'. Must be one of: best_shots, blur, duplicates, closed_eyes, low_score",
            )

    where_str = " AND ".join(where_clauses)

    sort_map = {
        "score_desc": "score DESC, id ASC",
        "newest": "created_at DESC, id DESC",
        "oldest": "created_at ASC, id ASC",
        "similarity": "similarity_group IS NULL, similarity_group ASC, score DESC",
        "sharpness_desc": "sharpness_score DESC, id ASC",
    }
    order_clause = sort_map.get((sort or "score_desc").lower().strip(), "score DESC, id ASC")

    return where_str, params, order_clause


@router.get(
    "/batches/{batch_id}/photos",
    response_model=PaginatedPhotosResponse,
)
def get_batch_photos(
    batch_id: str,
    category: Optional[str] = Query(None, description="Filter by category: people | stage | candid | group | other"),
    filter: Optional[str] = Query(None, description="Preset filter: best_shots | blur | duplicates | closed_eyes | low_score"),
    status: Optional[str] = Query(None, description="Filter by status: keep | review | reject"),
    sort: Optional[str] = Query("score_desc", description="Sort order: score_desc | newest | oldest | similarity | sharpness_desc"),
    page: int = Query(1, ge=1, description="Page number, 1-indexed"),
    page_size: int = Query(60, ge=1, le=200, description="Items per page"),
) -> PaginatedPhotosResponse:
    """
    Return paginated, filtered, and sorted photos for *batch_id*.

    Filters and sorting are applied directly in SQL for maximum performance.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # Check that batch exists
        exists = conn.execute(
            "SELECT 1 FROM photos WHERE batch_id = ? LIMIT 1", (batch_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(
                status_code=404,
                detail=f"No photos found for batch '{batch_id}'.",
            )

        where_str, params, order_clause = build_photos_query(
            batch_id=batch_id,
            category=category,
            status=status,
            filter=filter,
            sort=sort,
        )

        # Total matching items
        count_sql = f"SELECT COUNT(*) FROM photos WHERE {where_str}"
        total_matching = conn.execute(count_sql, params).fetchone()[0]

        # Paginated fetch
        offset = (page - 1) * page_size
        query = f"""
            SELECT id, filename, category, score, blur_detected,
                   closed_eyes_detected, duplicate, similarity_group,
                   recommendation, status
            FROM photos
            WHERE {where_str}
            ORDER BY {order_clause}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [page_size, offset]).fetchall()

        items = [
            BatchPhotoItem(
                id=r["id"],
                filename=r["filename"],
                thumbnail_url=f"/thumbnails/{batch_id}/{r['id']}.jpg",
                category=r["category"],
                score=r["score"],
                blur_detected=bool(r["blur_detected"]) if r["blur_detected"] is not None else None,
                closed_eyes_detected=bool(r["closed_eyes_detected"]) if r["closed_eyes_detected"] is not None else None,
                duplicate=bool(r["duplicate"]) if r["duplicate"] is not None else None,
                similarity_group=r["similarity_group"],
                recommendation=r["recommendation"],
                status=r["status"],
            )
            for r in rows
        ]

        return PaginatedPhotosResponse(
            photos=items,
            total=total_matching,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


# ── 3. PATCH /batches/{batch_id}/photos/status (Bulk status update) ───────────

@router.patch(
    "/batches/{batch_id}/photos/status",
    response_model=BulkStatusUpdateResponse,
)
def bulk_update_photo_status(
    batch_id: str,
    body: BulkStatusUpdateRequest,
) -> BulkStatusUpdateResponse:
    """
    Bulk update the workflow status for multiple photos in a batch atomically.
    """
    valid_statuses = {"keep", "review", "reject"}
    new_status = body.status.lower().strip()
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of: keep, review, reject",
        )

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        if body.photo_ids is not None:
            if not body.photo_ids:
                return BulkStatusUpdateResponse(updated_count=0)
            placeholders = ",".join("?" for _ in body.photo_ids)
            sql = f"UPDATE photos SET status = ? WHERE batch_id = ? AND id IN ({placeholders})"
            cursor = conn.execute(sql, [new_status, batch_id] + body.photo_ids)
            conn.commit()
            return BulkStatusUpdateResponse(updated_count=cursor.rowcount)
        else:
            # Apply to filtered/category set
            where_str, params, _ = build_photos_query(
                batch_id=batch_id,
                category=body.category,
                filter=body.filter,
            )
            sql = f"UPDATE photos SET status = ? WHERE {where_str}"
            cursor = conn.execute(sql, [new_status] + params)
            conn.commit()
            return BulkStatusUpdateResponse(updated_count=cursor.rowcount)
    finally:
        conn.close()


# ── 4. POST /batches/{batch_id}/export (Stream ZIP file of selected photos) ───

@router.post(
    "/batches/{batch_id}/export",
    tags=["Batches"],
)
def export_batch_photos(
    batch_id: str,
    body: Optional[ExportBatchRequest] = None,
):
    """
    Export selected photos as a downloadable ZIP archive.
    If photo_ids is omitted, defaults to all photos with status='keep'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if body and body.photo_ids:
            placeholders = ",".join("?" for _ in body.photo_ids)
            sql = f"SELECT id, filename FROM photos WHERE batch_id = ? AND id IN ({placeholders})"
            rows = conn.execute(sql, [batch_id] + body.photo_ids).fetchall()
        else:
            sql = "SELECT id, filename FROM photos WHERE batch_id = ? AND lower(status) = 'keep'"
            rows = conn.execute(sql, (batch_id,)).fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="No photos match the selection for export.",
        )

    batch_dir = _UPLOAD_DIR / batch_id
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = Path(temp_zip.name)
    temp_zip.close()

    seen_arcnames: set[str] = set()
    exported_count = 0
    skipped_count = 0

    with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            pid = r["id"]
            fname = r["filename"]
            matches = list(batch_dir.glob(f"{pid}.*")) if batch_dir.is_dir() else []
            if not matches:
                logger.warning("Export: file for photo %s (%s) not found on disk, skipping.", pid, fname)
                skipped_count += 1
                continue

            source_file = matches[0]
            arcname = fname
            if arcname in seen_arcnames:
                arcname = f"{pid[:8]}_{fname}"
            seen_arcnames.add(arcname)
            zf.write(source_file, arcname=arcname)
            exported_count += 1

    def stream_and_cleanup():
        try:
            with open(temp_zip_path, "rb") as f:
                while chunk := f.read(128 * 1024):
                    yield chunk
        finally:
            try:
                os.unlink(temp_zip_path)
            except Exception:
                pass

    filename = f"photosort_{batch_id}_selected.zip"
    return StreamingResponse(
        stream_and_cleanup(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Count": str(exported_count),
            "X-Skipped-Count": str(skipped_count),
        },
    )


# ── 5. GET /batches/{batch_id}/export/report (Download CSV report) ────────────

@router.get(
    "/batches/{batch_id}/export/report",
    tags=["Batches"],
)
def export_batch_report(batch_id: str):
    """
    Generate a summary & detailed CSV report of the batch matching dashboard figures.
    """
    thresholds = get_recommendation_thresholds()
    review_threshold = thresholds.get("review", 50.0)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN recommendation = 'keep' THEN 1 ELSE 0 END) AS best_shots,
                SUM(CASE WHEN lower(status) = 'keep' THEN 1 ELSE 0 END) AS selected_count,
                SUM(CASE WHEN lower(status) = 'review' THEN 1 ELSE 0 END) AS review_count,
                SUM(CASE WHEN lower(status) = 'reject' THEN 1 ELSE 0 END) AS reject_count,
                SUM(CASE WHEN blur_detected = 1 THEN 1 ELSE 0 END) AS blur_count,
                SUM(CASE WHEN duplicate = 1 THEN 1 ELSE 0 END) AS duplicate_count,
                SUM(CASE WHEN closed_eyes_detected = 1 THEN 1 ELSE 0 END) AS closed_eyes_count,
                SUM(CASE WHEN score IS NOT NULL AND score < ? THEN 1 ELSE 0 END) AS low_score_count
            FROM photos
            WHERE batch_id = ?
            """,
            (review_threshold, batch_id),
        ).fetchone()

        if not summary_row or summary_row["total"] == 0:
            raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

        photo_rows = conn.execute(
            """
            SELECT id, filename, category, score, sharpness_score, exposure_score,
                   face_score, composition_score, uniqueness_score,
                   recommendation, status, reasons
            FROM photos
            WHERE batch_id = ?
            ORDER BY score DESC, id ASC
            """,
            (batch_id,),
        ).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Summary Metrics
    writer.writerow(["=== BATCH CULLING SUMMARY ==="])
    writer.writerow(["Batch ID", batch_id])
    writer.writerow(["Total Photos", summary_row["total"] or 0])
    writer.writerow(["Kept", summary_row["selected_count"] or 0])
    writer.writerow(["Review", summary_row["review_count"] or 0])
    writer.writerow(["Rejected", summary_row["reject_count"] or 0])
    writer.writerow(["Blur Count", summary_row["blur_count"] or 0])
    writer.writerow(["Duplicate Count", summary_row["duplicate_count"] or 0])
    writer.writerow(["Closed Eyes Count", summary_row["closed_eyes_count"] or 0])
    writer.writerow([])

    # 2. Per-Photo Detail Breakdown
    writer.writerow(["=== PER-PHOTO BREAKDOWN ==="])
    writer.writerow([
        "Photo ID",
        "Filename",
        "Category",
        "Score",
        "Sharpness Score",
        "Exposure Score",
        "Face Score",
        "Composition Score",
        "Uniqueness Score",
        "Recommendation",
        "Status",
        "Reasons",
    ])

    for pr in photo_rows:
        reasons_str = ""
        if pr["reasons"]:
            try:
                r_list = json.loads(pr["reasons"])
                reasons_str = "; ".join(r_list) if isinstance(r_list, list) else str(pr["reasons"])
            except Exception:
                reasons_str = str(pr["reasons"])

        writer.writerow([
            pr["id"],
            pr["filename"],
            pr["category"] or "",
            f"{pr['score']:.1f}" if pr["score"] is not None else "",
            f"{pr['sharpness_score']:.1f}" if pr["sharpness_score"] is not None else "",
            f"{pr['exposure_score']:.1f}" if pr["exposure_score"] is not None else "",
            f"{pr['face_score']:.1f}" if pr["face_score"] is not None else "",
            f"{pr['composition_score']:.1f}" if pr["composition_score"] is not None else "",
            f"{pr['uniqueness_score']:.1f}" if pr["uniqueness_score"] is not None else "",
            pr["recommendation"] or "",
            pr["status"] or "",
            reasons_str,
        ])

    filename = f"photosort_{batch_id}_report.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 6. GET /batches/{batch_id}/errors (Batch Error Log) ──────────────────────

@router.get(
    "/batches/{batch_id}/errors",
    response_model=list[BatchErrorItem],
)
def get_batch_errors_endpoint(batch_id: str) -> list[BatchErrorItem]:
    """Return all errors (upload or analysis) logged for this batch."""
    from db import get_batch_errors
    errors = get_batch_errors(batch_id)
    return [
        BatchErrorItem(
            photo_id=e.get("photo_id"),
            filename=e.get("filename") or "unknown",
            stage=e.get("stage") or "pipeline",
            reason=e.get("reason") or "Unknown error",
        )
        for e in errors
    ]


# ── 7. POST /batches/{batch_id}/rescore (Fast Weight Rescoring) ──────────────

@router.post(
    "/batches/{batch_id}/rescore",
)
def rescore_batch_endpoint(batch_id: str):
    """
    Re-score a batch using current weights from scoring_weights.json.
    Re-computes composition, composite scores, and AI Picks without re-running heavy CV/CLIP.
    """
    from workers.job_runner import rescore_batch
    scored = rescore_batch(batch_id)
    return {
        "status": "rescored",
        "batch_id": batch_id,
        "rescored_count": len(scored),
    }
