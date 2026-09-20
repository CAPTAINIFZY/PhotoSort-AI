import os
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from routers import analysis, batches, clusters, photos, upload

load_dotenv()

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR      = os.getenv("UPLOAD_DIR",      str(_PROJECT_ROOT / "uploads/originals"))
THUMBNAIL_DIR   = os.getenv("THUMBNAIL_DIR",   str(_PROJECT_ROOT / "processed/thumbnails"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup / shutdown tasks."""
    # Ensure DB tables exist and any pending migrations are applied.
    init_db()
    # Ensure storage directories exist.
    os.makedirs(UPLOAD_DIR,    exist_ok=True)
    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    yield


app = FastAPI(
    title="PhotoSort AI",
    description="AI-powered event photo culling API",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(upload.router)
app.include_router(batches.router)
app.include_router(analysis.router)
app.include_router(clusters.router)
app.include_router(photos.router)

# ── Static file serving for thumbnails & originals ────────────────────────────
app.mount("/thumbnails", StaticFiles(directory=THUMBNAIL_DIR), name="thumbnails")
app.mount("/originals", StaticFiles(directory=UPLOAD_DIR), name="originals")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check() -> dict:
    """
    Returns the operational status of the API, database, and storage layer.

    Response shape:
        { "status": "ok", "db": <bool>, "storage": <bool> }
    """
    db_ok = False
    try:
        from db import engine
        from sqlmodel import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    storage_ok = os.path.isdir(UPLOAD_DIR) and os.path.isdir(THUMBNAIL_DIR)

    return {
        "status": "ok",
        "db": db_ok,
        "storage": storage_ok,
    }
