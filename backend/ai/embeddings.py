"""
ai/embeddings.py — CLIP image & text embeddings via open_clip.

Loads the ViT-B-32 model once at module import time and raises a clear
RuntimeError immediately if the model cannot be loaded — this prevents
silent per-image failures that are harder to diagnose.

Design notes
------------
- Device is always CPU; GPU is not required and not assumed.
- The model is loaded into a module-level singleton so worker processes
  each initialise it once and reuse it across many images.
- Embeddings are L2-normalised before return so cosine similarity
  reduces to a simple dot product.
- Images are pre-processed with open_clip's own transform pipeline
  (handles resizing, centre-crop, and normalisation).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import torch

# ── Model configuration ───────────────────────────────────────────────────────

_MODEL_NAME  = "ViT-B-32"
_PRETRAINED  = "openai"
_DEVICE      = "cpu"
_CACHE_DIR   = os.getenv("MODEL_CACHE_DIR", str(Path(__file__).resolve().parents[2] / "models"))

# ── Lazy-loaded singletons ────────────────────────────────────────────────────

_model     = None
_preprocess = None
_tokenizer  = None


def _load_model():
    """Load ViT-B-32 once; raise RuntimeError if it cannot be loaded."""
    global _model, _preprocess, _tokenizer
    if _model is not None:
        return _model, _preprocess, _tokenizer

    try:
        import open_clip
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "open_clip_torch is not installed. "
            "Run: pip install open-clip-torch"
        ) from exc

    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            _MODEL_NAME,
            pretrained=_PRETRAINED,
            device=_DEVICE,
            cache_dir=_CACHE_DIR,
        )
        model.eval()
        tokenizer = open_clip.get_tokenizer(_MODEL_NAME)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to load CLIP model '{_MODEL_NAME}/{_PRETRAINED}': {exc}"
        ) from exc

    _model      = model
    _preprocess = preprocess
    _tokenizer  = tokenizer
    return _model, _preprocess, _tokenizer


# Load model at module import (fail fast if loading fails)
_load_model()


# ── Public API ────────────────────────────────────────────────────────────────

def generate_embedding(image_path: str) -> np.ndarray:
    """
    Generate a normalised CLIP embedding for a single image.

    Parameters
    ----------
    image_path : str
        Absolute path to an image file (any format Pillow can read).

    Returns
    -------
    np.ndarray  shape (512,)  float32, L2-normalised.

    Raises
    ------
    RuntimeError  – model failed to load.
    ValueError    – image cannot be opened.
    """
    import torch
    from PIL import Image

    model, preprocess, _ = _load_model()

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:
        raise ValueError(f"Cannot open image '{image_path}': {exc}") from exc

    tensor = preprocess(img).unsqueeze(0).to(_DEVICE)   # (1, 3, 224, 224)

    with torch.no_grad():
        emb = model.encode_image(tensor)                 # (1, 512)
        emb = emb / emb.norm(dim=-1, keepdim=True)      # L2 normalise

    return emb.squeeze(0).cpu().numpy().astype(np.float32)


def embed_text_prompts(prompts: list[str]) -> np.ndarray:
    """
    Generate normalised CLIP embeddings for a list of text prompts.

    Parameters
    ----------
    prompts : list[str]

    Returns
    -------
    np.ndarray  shape (N, 512)  float32, L2-normalised row-wise.

    Raises
    ------
    RuntimeError  – model failed to load.
    """
    import torch

    model, _, tokenizer = _load_model()

    tokens = tokenizer(prompts).to(_DEVICE)             # (N, 77)

    with torch.no_grad():
        emb = model.encode_text(tokens)                  # (N, 512)
        emb = emb / emb.norm(dim=-1, keepdim=True)

    return emb.cpu().numpy().astype(np.float32)
