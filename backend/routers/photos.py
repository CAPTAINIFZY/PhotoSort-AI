"""
routers/photos.py — Photo detail, original image, and adjacent navigation endpoints.

Provides:
    GET /photos/{photo_id}          — Returns full analysis, scores, reasons, and cluster data.
    GET /photos/{photo_id}/original — Returns the full-resolution original image.
    GET /photos/{photo_id}/thumbnail— Returns the thumbnail JPEG.
    GET /photos/{photo_id}/adjacent — Returns prev_id and next_id in filtered gallery context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db import DB_PATH
from routers.batches import build_photos_query

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(_PROJECT_ROOT / "uploads/originals")))
_THUMBNAIL_DIR = Path(os.getenv("THUMBNAIL_DIR", str(_PROJECT_ROOT / "processed/thumbnails")))

router = APIRouter(tags=["Photos"])


class ClusterMember(BaseModel):
    id: str
    thumbnail_url: str
    score: Optional[float] = None
    is_ai_pick: bool


class PhotoCluster(BaseModel):
    similarity_group: int
    ai_pick_id: str
    members: list[ClusterMember]


class AdjacentPhotosResponse(BaseModel):
    prev_id: Optional[str] = None
    next_id: Optional[str] = None


class PhotoStatusUpdateRequest(BaseModel):
    status: str


class PhotoDetailResponse(BaseModel):
    id:                         str
    filename:                   str
    thumbnail_url:              str
    original_url:               str
    batch_id:                   Optional[str] = None
    category:                   Optional[str] = None

    # Scores
    score:                      Optional[float] = None
    sharpness_score:            Optional[float] = None
    exposure_score:             Optional[float] = None
    composition_score:          Optional[float] = None
    face_score:                 Optional[float] = None
    uniqueness_score:           Optional[float] = None

    # Raw metrics
    mean_brightness:            Optional[float] = None
    clipped_shadows_pct:        Optional[float] = None
    clipped_highlights_pct:     Optional[float] = None
    face_count:                 Optional[int] = None
    face_bboxes:                Optional[list[dict]] = None
    closed_eyes_detected:       Optional[bool] = None
    possible_closed_eyes_count: Optional[int] = None
    blur_detected:              Optional[bool] = None

    # Similarity & Deduplication
    duplicate:                  Optional[bool] = None
    similarity_group:           Optional[int] = None
    cluster:                    Optional[PhotoCluster] = None

    # AI Recommendation
    recommendation:             Optional[str] = None
    reasons:                    Optional[list[str]] = None

    # System status
    status:                     Optional[str] = None
    processing_error:           Optional[str] = None
    created_at:                 Optional[str] = None


@router.get(
    "/photos/{photo_id}",
    response_model=PhotoDetailResponse,
)
def get_photo_detail(photo_id: str) -> PhotoDetailResponse:
    """
    Return full analysis, composition metrics, scores, recommendation, reasons,
    and similarity cluster information for a photo.

    Raises 404 if photo is not found.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, filename, batch_id, category, score,
                   sharpness_score, exposure_score, composition_score,
                   face_score, uniqueness_score, mean_brightness,
                   clipped_shadows_pct, clipped_highlights_pct,
                   face_count, face_bboxes, closed_eyes_detected,
                   possible_closed_eyes_count, blur_detected,
                   duplicate, similarity_group, recommendation,
                   reasons, status, processing_error, created_at
            FROM photos
            WHERE id = ?
            """,
            (photo_id,),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Photo '{photo_id}' not found.",
            )

        # Deserialize JSON fields
        reasons_list = None
        if row["reasons"]:
            try:
                reasons_list = json.loads(row["reasons"])
            except Exception:
                reasons_list = [row["reasons"]]

        face_bboxes_list = None
        if row["face_bboxes"]:
            try:
                face_bboxes_list = json.loads(row["face_bboxes"])
            except Exception:
                face_bboxes_list = None

        batch_id = row["batch_id"]
        thumbnail_url = f"/thumbnails/{batch_id}/{photo_id}.jpg" if batch_id else f"/photos/{photo_id}/thumbnail"

        # Determine original URL
        original_url = f"/photos/{photo_id}/original"
        if batch_id:
            batch_orig_dir = _UPLOAD_DIR / batch_id
            if batch_orig_dir.is_dir():
                matches = list(batch_orig_dir.glob(f"{photo_id}.*"))
                if matches:
                    original_url = f"/originals/{batch_id}/{matches[0].name}"

        # Similarity cluster logic
        cluster_obj: Optional[PhotoCluster] = None
        sim_group = row["similarity_group"]
        if sim_group is not None and batch_id:
            cluster_rows = conn.execute(
                """
                SELECT id, score, duplicate, batch_id
                FROM photos
                WHERE batch_id = ? AND similarity_group = ?
                ORDER BY (CASE WHEN duplicate = 0 THEN 0 ELSE 1 END) ASC, score DESC, id ASC
                """,
                (batch_id, sim_group),
            ).fetchall()

            if cluster_rows:
                # Find AI Pick ID (duplicate == 0 or first)
                ai_pick_id = None
                for cr in cluster_rows:
                    if not cr["duplicate"]:
                        ai_pick_id = cr["id"]
                        break
                if not ai_pick_id and cluster_rows:
                    ai_pick_id = cluster_rows[0]["id"]

                members = [
                    ClusterMember(
                        id=cr["id"],
                        thumbnail_url=f"/thumbnails/{cr['batch_id']}/{cr['id']}.jpg",
                        score=cr["score"],
                        is_ai_pick=(cr["id"] == ai_pick_id),
                    )
                    for cr in cluster_rows
                ]

                cluster_obj = PhotoCluster(
                    similarity_group=sim_group,
                    ai_pick_id=ai_pick_id,
                    members=members,
                )

        return PhotoDetailResponse(
            id=row["id"],
            filename=row["filename"],
            thumbnail_url=thumbnail_url,
            original_url=original_url,
            batch_id=batch_id,
            category=row["category"],
            score=row["score"],
            sharpness_score=row["sharpness_score"],
            exposure_score=row["exposure_score"],
            composition_score=row["composition_score"],
            face_score=row["face_score"],
            uniqueness_score=row["uniqueness_score"],
            mean_brightness=row["mean_brightness"],
            clipped_shadows_pct=row["clipped_shadows_pct"],
            clipped_highlights_pct=row["clipped_highlights_pct"],
            face_count=row["face_count"],
            face_bboxes=face_bboxes_list,
            closed_eyes_detected=bool(row["closed_eyes_detected"]) if row["closed_eyes_detected"] is not None else None,
            possible_closed_eyes_count=row["possible_closed_eyes_count"],
            blur_detected=bool(row["blur_detected"]) if row["blur_detected"] is not None else None,
            duplicate=bool(row["duplicate"]) if row["duplicate"] is not None else None,
            similarity_group=sim_group,
            cluster=cluster_obj,
            recommendation=row["recommendation"],
            reasons=reasons_list,
            status=row["status"],
            processing_error=row["processing_error"],
            created_at=row["created_at"],
        )
    finally:
        conn.close()


@router.get(
    "/photos/{photo_id}/original",
    tags=["Photos"],
)
def get_photo_original(photo_id: str):
    """
    Return the full-resolution original image file for a given photo ID.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute("SELECT batch_id, filename FROM photos WHERE id = ?", (photo_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Photo '{photo_id}' not found.",
        )

    batch_id = row[0]
    if not batch_id:
        raise HTTPException(
            status_code=404,
            detail=f"Photo '{photo_id}' has no associated batch.",
        )

    batch_dir = _UPLOAD_DIR / batch_id
    matches = list(batch_dir.glob(f"{photo_id}.*")) if batch_dir.is_dir() else []
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"Original image for photo '{photo_id}' not found on disk.",
        )

    file_path = matches[0]
    ext = file_path.suffix.lower()
    media_type = "image/jpeg"
    if ext == ".png":
        media_type = "image/png"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext in (".heic", ".heif"):
        media_type = "image/heic"

    return FileResponse(str(file_path), media_type=media_type)


@router.get(
    "/photos/{photo_id}/thumbnail",
    tags=["Photos"],
)
def get_photo_thumbnail(photo_id: str):
    """
    Return the JPEG thumbnail image file for a given photo ID.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute("SELECT batch_id FROM photos WHERE id = ?", (photo_id,)).fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        raise HTTPException(
            status_code=404,
            detail=f"Photo '{photo_id}' not found.",
        )

    batch_id = row[0]
    thumb_path = _THUMBNAIL_DIR / batch_id / f"{photo_id}.jpg"
    if not thumb_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Thumbnail for photo '{photo_id}' not found on disk.",
        )

    return FileResponse(str(thumb_path), media_type="image/jpeg")


@router.get(
    "/photos/{photo_id}/adjacent",
    response_model=AdjacentPhotosResponse,
    tags=["Photos"],
)
def get_adjacent_photos(
    photo_id: str,
    batch_id: Optional[str] = Query(None, description="Batch ID context"),
    category: Optional[str] = Query(None, description="Filter by category"),
    filter: Optional[str] = Query(None, description="Preset filter"),
    status: Optional[str] = Query(None, description="Filter by status"),
    sort: Optional[str] = Query("score_desc", description="Sort order"),
) -> AdjacentPhotosResponse:
    """
    Return previous and next photo IDs within the given filtered and sorted gallery context.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        actual_batch_id = batch_id
        if not actual_batch_id:
            row = conn.execute("SELECT batch_id FROM photos WHERE id = ?", (photo_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Photo '{photo_id}' not found.")
            actual_batch_id = row["batch_id"]

        if not actual_batch_id:
            return AdjacentPhotosResponse(prev_id=None, next_id=None)

        where_str, params, order_clause = build_photos_query(
            batch_id=actual_batch_id,
            category=category,
            status=status,
            filter=filter,
            sort=sort,
        )

        query = f"SELECT id FROM photos WHERE {where_str} ORDER BY {order_clause}"
        rows = conn.execute(query, params).fetchall()
        id_list = [r["id"] for r in rows]

        try:
            idx = id_list.index(photo_id)
            prev_id = id_list[idx - 1] if idx > 0 else None
            next_id = id_list[idx + 1] if idx < len(id_list) - 1 else None
        except ValueError:
            prev_id = None
            next_id = None

        return AdjacentPhotosResponse(prev_id=prev_id, next_id=next_id)
    finally:
        conn.close()


@router.patch(
    "/photos/{photo_id}/status",
    response_model=PhotoDetailResponse,
    tags=["Photos"],
)
def update_photo_status(
    photo_id: str,
    body: PhotoStatusUpdateRequest,
) -> PhotoDetailResponse:
    """
    Manually override a photo's workflow status (keep | review | reject).

    Does not modify score, recommendation, or disk files.
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
        cursor = conn.execute("UPDATE photos SET status = ? WHERE id = ?", (new_status, photo_id))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Photo '{photo_id}' not found.",
            )
    finally:
        conn.close()

    return get_photo_detail(photo_id)

