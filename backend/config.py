"""
config.py — Centralised settings loaded once at import time.

All values are read from environment variables (via .env) with sensible
defaults.  Two public interfaces are provided:

    get_weights()        → dict from scoring_weights.json
    get_upload_config()  → dict with upload / thumbnail settings
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Scoring weights ───────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "scoring_weights.json"
)
_WEIGHTS_PATH = Path(os.getenv("WEIGHTS_PATH", str(_DEFAULT_WEIGHTS_PATH)))

try:
    with open(_WEIGHTS_PATH, "r", encoding="utf-8") as _f:
        _weights: dict = json.load(_f)
except FileNotFoundError as exc:
    raise RuntimeError(
        f"scoring_weights.json not found at {_WEIGHTS_PATH}. "
        "Ensure the config/ directory exists and contains the file."
    ) from exc


def get_weights() -> dict:
    """Return the scoring weights dictionary, dynamically re-reading from disk."""
    global _weights
    try:
        with open(_WEIGHTS_PATH, "r", encoding="utf-8") as f:
            _weights = json.load(f)
    except Exception:
        pass
    return _weights


# ── Upload / storage settings ─────────────────────────────────────────────────

def _parse_extensions(raw: str) -> frozenset[str]:
    """Parse a comma-separated list of extensions into a normalised frozenset."""
    return frozenset(
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in raw.split(",")
        if ext.strip()
    )


_upload_config: dict = {
    "max_file_size_mb": float(os.getenv("MAX_FILE_SIZE_MB", "25")),
    "allowed_extensions": _parse_extensions(
        os.getenv("ALLOWED_EXTENSIONS", ".jpg,.jpeg,.png,.webp")
    ),
    "thumbnail_max_dimension": int(os.getenv("THUMBNAIL_MAX_DIMENSION", "480")),
}


def get_upload_config() -> dict:
    """
    Return upload-related settings:

        max_file_size_mb        float  – maximum accepted file size in MB
        allowed_extensions      frozenset[str]  – e.g. {'.jpg', '.jpeg', ...}
        thumbnail_max_dimension int    – longest edge of generated thumbnails
    """
    return _upload_config
