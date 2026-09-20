"""
routers/clusters.py — GET /batches/{batch_id}/clusters

Returns similarity clusters for a completed batch in a format suitable
for the dashboard and detail views (Phase 6+).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import DB_PATH

router = APIRouter(tags=["Clusters"])


# ── Response model ────────────────────────────────────────────────────────────

class ClusterItem(BaseModel):
    similarity_group: int
    photo_ids:        list[str]
    ai_pick:          str      # photo_id of the cluster representative


class ClustersResponse(BaseModel):
    batch_id: str
    clusters: list[ClusterItem]
    solo_count: int   # photos not in any cluster


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get(
    "/batches/{batch_id}/clusters",
    response_model=ClustersResponse,
)
def get_batch_clusters(batch_id: str) -> ClustersResponse:
    """
    Return all similarity groups for the batch.

    - Only photos with similarity_group IS NOT NULL are included in clusters.
    - Within each cluster, the AI pick is the photo where duplicate=FALSE.
    - Returns 404 if the batch has no photos.
    - Returns 200 with clusters=[] if no duplicates were found.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, similarity_group, duplicate
            FROM photos
            WHERE batch_id = ?
            ORDER BY similarity_group, id
            """,
            (batch_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No photos found for batch '{batch_id}'.",
        )

    # Separate clustered from solo
    from collections import defaultdict

    group_pids: dict[int, list[str]]  = defaultdict(list)
    group_pick: dict[int, str]        = {}
    solo_count  = 0

    for row in rows:
        sg = row["similarity_group"]
        if sg is None:
            solo_count += 1
            continue

        group_pids[sg].append(row["id"])
        # The representative has duplicate=0 (False)
        if not row["duplicate"]:
            group_pick[sg] = row["id"]

    clusters: list[ClusterItem] = []
    for sg, pids in sorted(group_pids.items()):
        # Fallback: if no representative recorded, pick first alphabetically
        pick = group_pick.get(sg, pids[0])
        clusters.append(ClusterItem(
            similarity_group=sg,
            photo_ids=pids,
            ai_pick=pick,
        ))

    return ClustersResponse(
        batch_id=batch_id,
        clusters=clusters,
        solo_count=solo_count,
    )
