import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import DateTime, String, text as sa_text
from sqlmodel import Boolean, Column, Field, Session, SQLModel, create_engine, text

load_dotenv()

# Defaults are project-relative rather than process-CWD-relative, so running
# ``uvicorn`` from either the repository root or backend/ uses the same data.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(_PROJECT_ROOT / "photosort.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


class Photo(SQLModel, table=True):
    """ORM model for the `photos` table."""

    __tablename__ = "photos"

    id: str = Field(primary_key=True)
    filename: str
    batch_id: Optional[str] = None          # groups photos from one upload session
    category: Optional[str] = None

    # Composite score
    score: Optional[float] = None

    # Individual sub-scores
    sharpness_score: Optional[float] = None
    exposure_score: Optional[float] = None
    composition_score: Optional[float] = None
    face_score: Optional[float] = None
    uniqueness_score: Optional[float] = None

    # Raw CV measurements (persisted for scoring engine use in later phases)
    mean_brightness: Optional[float] = None
    clipped_shadows_pct: Optional[float] = None
    clipped_highlights_pct: Optional[float] = None
    possible_closed_eyes_count: Optional[int] = None

    # Detection flags
    blur_detected: Optional[bool] = Field(default=None, sa_column=Column(Boolean))
    closed_eyes_detected: Optional[bool] = Field(default=None, sa_column=Column(Boolean))
    face_count: Optional[int] = None
    face_bboxes: Optional[str] = None  # JSON-serialized list of detected face bounding boxes
    duplicate: Optional[bool] = Field(default=None, sa_column=Column(Boolean))

    # Grouping
    similarity_group: Optional[int] = None

    # AI output
    recommendation: Optional[str] = None
    reasons: Optional[str] = None

    # Processing error (set when pipeline fails on this photo)
    processing_error: Optional[str] = None

    # Workflow — use sa_column so the DEFAULT clause is emitted in DDL
    # and raw sqlite3 inserts (without SQLModel) also receive the defaults.
    status: Optional[str] = Field(
        default="review",
        sa_column=Column(String, server_default="review", nullable=True),
    )
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(
            String,
            server_default=sa_text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
    )


class AnalysisJob(SQLModel, table=True):
    """Tracks per-batch analysis job progress."""

    __tablename__ = "jobs"

    batch_id:    str           = Field(primary_key=True)
    total:       int           = Field(default=0)
    processed:   int           = Field(default=0)
    failed:      int           = Field(default=0)
    status:      Optional[str] = Field(
        default="pending",
        sa_column=Column(String, server_default="pending", nullable=True),
    )
    started_at:  Optional[str] = None
    finished_at: Optional[str] = None


def init_db() -> None:
    """Create all tables and apply any pending schema migrations."""
    SQLModel.metadata.create_all(engine)

    with engine.connect() as conn:
        # ── photos table (idempotent) ──────────────────────────────────────
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    id                          TEXT PRIMARY KEY,
                    filename                    TEXT,
                    batch_id                    TEXT,
                    category                    TEXT,
                    score                       REAL,
                    sharpness_score             REAL,
                    exposure_score              REAL,
                    composition_score           REAL,
                    face_score                  REAL,
                    uniqueness_score            REAL,
                    mean_brightness             REAL,
                    clipped_shadows_pct         REAL,
                    clipped_highlights_pct      REAL,
                    possible_closed_eyes_count  INTEGER,
                    blur_detected               BOOLEAN,
                    closed_eyes_detected        BOOLEAN,
                    face_count                  INTEGER,
                    duplicate                   BOOLEAN,
                    similarity_group            INTEGER,
                    recommendation              TEXT,
                    reasons                     TEXT,
                    processing_error            TEXT,
                    status                      TEXT DEFAULT 'review',
                    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        # ── jobs table (idempotent) ────────────────────────────────────────
        # ── jobs table (idempotent) ────────────────────────────────────────
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    batch_id    TEXT PRIMARY KEY,
                    total       INTEGER DEFAULT 0,
                    processed   INTEGER DEFAULT 0,
                    failed      INTEGER DEFAULT 0,
                    status      TEXT    DEFAULT 'pending',
                    started_at  TEXT,
                    finished_at TEXT
                )
                """
            )
        )

        # ── batch_errors table (idempotent) ────────────────────────────────
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS batch_errors (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id    TEXT NOT NULL,
                    photo_id    TEXT,
                    filename    TEXT,
                    stage       TEXT,
                    reason      TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        # ── Live migrations (idempotent — OperationalError = column exists) ─
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN batch_id TEXT")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN mean_brightness REAL")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN clipped_shadows_pct REAL")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN clipped_highlights_pct REAL")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN possible_closed_eyes_count INTEGER")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN processing_error TEXT")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN category TEXT")
        _safe_alter(conn, "ALTER TABLE photos ADD COLUMN face_bboxes TEXT")

        conn.commit()

    # Enable WAL mode for safe concurrent reads during analysis.
    # Must be set outside the transaction block.
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.commit()


def _safe_alter(conn, sql: str) -> None:
    """Run an ALTER TABLE, silently ignoring 'duplicate column' errors."""
    try:
        conn.execute(text(sql))
    except Exception:
        pass


def get_session():
    """Yield a database session (dependency-injectable)."""
    with Session(engine) as session:
        yield session


# ── DB write helpers (used by workers — no ORM, direct SQLite writes) ────────

def update_photo_analysis(photo_id: str, data: dict) -> None:
    """
    Write CV pipeline and scoring results into the photos row identified by photo_id.

    Uses a direct sqlite3 connection (not SQLModel) so it is safe to call
    from worker sub-processes that don't share the SQLAlchemy engine.
    """
    import json
    import sqlite3

    fields_map = {
        "sharpness_score":            "sharpness_score",
        "mean_brightness":            "mean_brightness",
        "clipped_shadows_pct":        "clipped_shadows_pct",
        "clipped_highlights_pct":     "clipped_highlights_pct",
        "face_count":                 "face_count",
        "face_bboxes":                "face_bboxes",
        "closed_eyes_detected":       "closed_eyes_detected",
        "possible_closed_eyes_count": "possible_closed_eyes_count",
        "processing_error":           "processing_error",
        "category":                   "category",
        "composition_score":          "composition_score",
        "face_score":                 "face_score",
        "uniqueness_score":           "uniqueness_score",
        "exposure_score":             "exposure_score",
        "score":                      "score",
        "recommendation":             "recommendation",
        "reasons":                    "reasons",
        "blur_detected":              "blur_detected",
        "duplicate":                  "duplicate",
        "similarity_group":           "similarity_group",
        "status":                     "status",
    }

    updates = {}
    for src_key, db_col in fields_map.items():
        if src_key in data:
            val = data[src_key]
            if src_key in ("face_bboxes", "reasons") and isinstance(val, (list, dict)):
                val = json.dumps(val)
            updates[db_col] = val

    if not updates:
        return

    # Mark status: if there was a processing_error AND all scores are null,
    # mark 'error'; otherwise keep 'review' (scoring phase will update later).
    if data.get("processing_error") and data.get("sharpness_score") is None and "status" not in data:
        updates["status"] = "error"

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values     = list(updates.values()) + [photo_id]

    db_path = DB_PATH
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute(f"UPDATE photos SET {set_clause} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def upsert_job(batch_id: str, **kwargs) -> None:
    """
    Insert or update a jobs row.  Keyword args are column name → value.
    Uses direct sqlite3 for process-safety.
    """
    import sqlite3

    allowed = {"total", "processed", "failed", "status", "started_at", "finished_at"}
    kwargs  = {k: v for k, v in kwargs.items() if k in allowed}

    db_path = DB_PATH
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        # Ensure row exists
        # SQLModel's Python-side defaults are not SQLite server defaults on
        # databases created by ``create_all``.  Supply all NOT NULL counters
        # explicitly so this helper works for both fresh and migrated DBs.
        conn.execute(
            """INSERT OR IGNORE INTO jobs
               (batch_id, total, processed, failed, status)
               VALUES (?, 0, 0, 0, 'pending')""",
            (batch_id,),
        )
        if kwargs:
            set_clause = ", ".join(f"{k} = ?" for k in kwargs)
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE batch_id = ?",
                [*kwargs.values(), batch_id],
            )
        conn.commit()
    finally:
        conn.close()


def get_job(batch_id: str) -> dict | None:
    """Return the jobs row for batch_id, or None if not found."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM jobs WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_batch_error(
    batch_id: str,
    filename: str,
    stage: str,
    reason: str,
    photo_id: str | None = None,
) -> None:
    """Record an error for a file within a batch."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute(
            """INSERT INTO batch_errors (batch_id, photo_id, filename, stage, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (batch_id, photo_id, filename, stage, reason),
        )
        conn.commit()
    finally:
        conn.close()


def get_batch_errors(batch_id: str) -> list[dict]:
    """Retrieve all recorded errors for a batch."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, batch_id, photo_id, filename, stage, reason, created_at
               FROM batch_errors
               WHERE batch_id = ?
               ORDER BY id ASC""",
            (batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

