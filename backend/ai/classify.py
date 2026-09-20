"""
ai/classify.py — Zero-shot photo category classification via CLIP.

Category prompts are embedded once at module load and cached.  Subsequent
calls to classify_photo() are pure numpy dot-products (< 1 µs each).

Categories are intentionally broad; fine-grained classification belongs
in a later phase with a supervised head or more prompts.
"""

from __future__ import annotations

import numpy as np

# ── Category definitions ──────────────────────────────────────────────────────

CATEGORY_PROMPTS: dict[str, str] = {
    "people":  "a photo of a person or people",
    "stage":   "a photo of a stage, presentation, or performance",
    "candid":  "a candid, unposed photo of people interacting",
    "group":   "a posed group photo",
    "other":   "a photo that doesn't clearly show people or a stage",
}

_LABELS: list[str] = list(CATEGORY_PROMPTS.keys())
_PROMPTS: list[str] = list(CATEGORY_PROMPTS.values())

from ai.embeddings import embed_text_prompts

# ── Cached text embeddings (computed once at module load) ────────────────────
_text_embeddings: np.ndarray = embed_text_prompts(_PROMPTS)


# ── Public API ────────────────────────────────────────────────────────────────

def classify_photo(image_embedding: np.ndarray) -> str:
    """
    Return the category label whose text embedding is closest to the image.

    Parameters
    ----------
    image_embedding : np.ndarray  shape (512,)  — L2-normalised CLIP vector.

    Returns
    -------
    str  — one of the keys in CATEGORY_PROMPTS.
    """
    # Both sides are L2-normalised → dot product = cosine similarity
    sims  = _text_embeddings @ image_embedding           # (N,)
    best  = int(np.argmax(sims))
    return _LABELS[best]


def preload() -> None:
    """Already loaded at module import."""
    pass
