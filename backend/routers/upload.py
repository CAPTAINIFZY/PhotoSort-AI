"""
routers/upload.py — POST /upload

Accepts multipart/form-data with one or more image files.
Validates, saves originals (streamed), generates thumbnails via Pillow,
and inserts a row into the `photos` table for each accepted file.

One failed file never aborts the batch — all results are collected and
returned in the response.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel
from sqlmodel import Session

from config import get_upload_config
from db import Photo, get_session, record_batch_error

router = APIRouter(tags=["Upload"])

# ── Config ────────────────────────────────────────────────────────────────────

_cfg = get_upload_config()
ALLOWED_EXTENSIONS: frozenset[str] = _cfg["allowed_extensions"]
MAX_FILE_SIZE_BYTES: int = int(_cfg["max_file_size_mb"] * 1024 * 1024)
THUMBNAIL_MAX_DIM: int = _cfg["thumbnail_max_dimension"]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR    = Path(os.getenv("UPLOAD_DIR",    str(_PROJECT_ROOT / "uploads/originals")))
THUMBNAIL_DIR = Path(os.getenv("THUMBNAIL_DIR", str(_PROJECT_ROOT / "processed/thumbnails")))

# Stream chunk size for disk writes (256 KiB)
_CHUNK = 256 * 1024


# ── Pydantic response models ──────────────────────────────────────────────────

class AcceptedFile(BaseModel):
    photo_id: str
    filename: str


class RejectedFile(BaseModel):
    filename: str
    reason: str


class UploadResponse(BaseModel):
    batch_id: str
    accepted_count: int
    rejected_count: int
    accepted: list[AcceptedFile]
    rejected: list[RejectedFile]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _thumb_size(width: int, height: int, max_dim: int) -> tuple[int, int]:
    """Return (w, h) scaled so the longest edge equals max_dim."""
    if width >= height:
        return max_dim, max(1, round(height * max_dim / width))
    return max(1, round(width * max_dim / height)), max_dim


async def _stream_to_disk(file: UploadFile, dest: Path) -> int:
    """
    Write *file* to *dest* in chunks.  Returns the total byte count.
    Raises ValueError if the file exceeds MAX_FILE_SIZE_BYTES.
    """
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(dest, "wb") as out:
        while True:
            chunk = await file.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_SIZE_BYTES:
                raise ValueError("file_too_large")
            await out.write(chunk)
    return total


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_photos(
    files: list[UploadFile],
    session: Annotated[Session, Depends(get_session)],
) -> UploadResponse:
    """
    Upload one or more image files for a new batch.

    - Validates extension and size.
    - Saves original to `uploads/originals/{batch_id}/{photo_id}.{ext}`.
    - Generates a 480-px thumbnail to `processed/thumbnails/{batch_id}/{photo_id}.jpg`.
    - Inserts a `photos` row (status='review', all score fields NULL).
    - Returns accepted / rejected summary — one bad file never aborts the batch.
    """
    batch_id = str(uuid4())
    accepted: list[AcceptedFile] = []
    rejected: list[RejectedFile] = []

    for file in files:
        filename = file.filename or "unknown"

        try:
            # ── 1. Extension check ────────────────────────────────────────
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValueError("unsupported_format")

            # ── 2. Size check + streamed write ────────────────────────────
            photo_id  = str(uuid4())
            orig_path = UPLOAD_DIR / batch_id / f"{photo_id}{ext}"

            try:
                file_size = await _stream_to_disk(file, orig_path)
            except ValueError:
                # Clean up the partial file
                orig_path.unlink(missing_ok=True)
                raise

            # ── 3. Validate image + generate thumbnail ────────────────────
            thumb_path = THUMBNAIL_DIR / batch_id / f"{photo_id}.jpg"
            thumb_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                with Image.open(orig_path) as img:
                    img = ImageOps.exif_transpose(img)
                    w, h = _thumb_size(img.width, img.height, THUMBNAIL_MAX_DIM)
                    thumb = img.resize((w, h), Image.LANCZOS)
                    # Convert palette/RGBA for JPEG compatibility
                    if thumb.mode not in ("RGB", "L"):
                        thumb = thumb.convert("RGB")
                    thumb.save(thumb_path, "JPEG", quality=85, optimize=True)
            except (UnidentifiedImageError, OSError, Exception) as exc:
                # Catches: UnidentifiedImageError, TruncatedFile (OSError subclass),
                # DecompressionBombError, and any other Pillow decode failure.
                orig_path.unlink(missing_ok=True)
                raise ValueError("corrupt_image") from exc

            # ── 4. Insert DB row ──────────────────────────────────────────
            photo = Photo(
                id=photo_id,
                filename=filename,
                batch_id=batch_id,
                status="review",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(photo)
            session.commit()

            accepted.append(AcceptedFile(photo_id=photo_id, filename=filename))

        except ValueError as exc:
            reason = str(exc) if str(exc) in {
                "unsupported_format", "file_too_large", "corrupt_image"
            } else "unknown_error"
            rejected.append(RejectedFile(filename=filename, reason=reason))
            record_batch_error(batch_id=batch_id, filename=filename, stage="upload", reason=reason)

        except Exception as exc:  # noqa: BLE001
            # Unexpected error — record and continue
            reason = f"server_error: {exc}"
            rejected.append(RejectedFile(filename=filename, reason=reason))
            record_batch_error(batch_id=batch_id, filename=filename, stage="upload", reason=reason)

    return UploadResponse(
        batch_id=batch_id,
        accepted_count=len(accepted),
        rejected_count=len(rejected),
        accepted=accepted,
        rejected=rejected,
    )
