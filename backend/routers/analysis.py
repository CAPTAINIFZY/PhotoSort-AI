"""
routers/analysis.py — Batch analysis trigger and status endpoints.

POST /batches/{batch_id}/analyze
    Validates the batch exists and isn't already running, then launches
    run_batch_analysis in FastAPI BackgroundTasks.

GET /batches/{batch_id}/status
    Returns current jobs row fields.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from db import DB_PATH, get_job, upsert_job

router = APIRouter(tags=["Analysis"])


# ── Response models ───────────────────────────────────────────────────────────

class StartAnalysisResponse(BaseModel):
    status: str
    batch_id: str
    total: int


class JobStatusResponse(BaseModel):
    batch_id:    str
    status:      str | None
    total:       int
    processed:   int
    failed:      int
    started_at:  str | None
    finished_at: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count_batch_photos(batch_id: str) -> int:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _claim_analysis_job(batch_id: str, total: int) -> None:
    """Atomically reserve a batch for analysis.

    Checking a job and writing ``pending`` in separate transactions lets two
    near-simultaneous POSTs both launch workers.  ``BEGIN IMMEDIATE`` makes the
    check-and-claim one short SQLite transaction; pending is deliberately
    treated as running for this purpose.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM jobs WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if row and row[0] in ("pending", "running", "completed"):
            raise HTTPException(
                status_code=409,
                detail=f"Batch '{batch_id}' is already {row[0]}.",
            )
        conn.execute(
            """
            INSERT INTO jobs (batch_id, total, processed, failed, status,
                              started_at, finished_at)
            VALUES (?, ?, 0, 0, 'pending', NULL, NULL)
            ON CONFLICT(batch_id) DO UPDATE SET
                total = excluded.total, processed = 0, failed = 0,
                status = 'pending', started_at = NULL, finished_at = NULL
            """,
            (batch_id, total),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/batches/{batch_id}/analyze",
    response_model=StartAnalysisResponse,
    status_code=202,
)
def start_analysis(
    batch_id: str,
    background_tasks: BackgroundTasks,
) -> StartAnalysisResponse:
    """
    Kick off CV analysis for all photos in *batch_id*.

    - Returns 404 if the batch has no photos.
    - Returns 409 if the batch is already running or completed.
    - Returns 202 Accepted immediately; analysis runs in the background.
    """
    total = _count_batch_photos(batch_id)
    if total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No photos found for batch '{batch_id}'.",
        )

    # Reserve it before scheduling so repeat POSTs are consistently rejected,
    # including the tiny interval before the worker changes pending → running.
    _claim_analysis_job(batch_id, total)

    # Import here so the heavy CV imports happen lazily.
    from workers.job_runner import run_batch_analysis

    background_tasks.add_task(run_batch_analysis, batch_id)

    return StartAnalysisResponse(
        status="started",
        batch_id=batch_id,
        total=total,
    )


@router.get(
    "/batches/{batch_id}/status",
    response_model=JobStatusResponse,
)
def get_batch_status(batch_id: str) -> JobStatusResponse:
    """
    Return the current analysis job status for *batch_id*.

    - Returns 404 if no job row exists yet (batch hasn't been analysed).
    """
    job = get_job(batch_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis job found for batch '{batch_id}'.",
        )
    return JobStatusResponse(
        batch_id=batch_id,
        status=job.get("status"),
        total=job.get("total", 0),
        processed=job.get("processed", 0),
        failed=job.get("failed", 0),
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
    )
