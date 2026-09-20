# PhotoSort AI — Model Weights Directory

This directory (`models/`) serves as the local cache for machine learning model files used by PhotoSort AI.

> **Note on GitHub Uploads:**  
> The actual model weight files and caches (totalling ~1.2 GB) are **intentionally excluded from Git** via `.gitignore` to keep the repository lightweight and adhere to GitHub's 100 MB single-file limit.

---

## Required Models

PhotoSort AI uses the following computer vision models:

| Model | File / Cache | Size | Purpose |
|---|---|---|---|
| **MediaPipe Face Landmarker** | `face_landmarker.task` | ~3.7 MB | 478-point facial mesh, blink/closed-eye detection |
| **MediaPipe BlazeFace** | `blaze_face_short_range.tflite` | ~230 KB | Rapid face detection & bounding box estimation |
| **OpenCLIP (ViT-B-32)** | `models--timm--vit_base_patch32_clip_224.openai/` | ~350 MB | Visual embeddings, event classification, similarity clustering |

---

## How to Get the Models

### Option A: Automatic Download (Recommended)
You do not need to download anything manually. When you start the PhotoSort AI backend and run your first photo analysis batch, the system automatically checks for these models and downloads them to this directory.

### Option B: Pre-download Helper Script
If you prefer to download all model files ahead of time before running the backend:

```bash
# Run from repository root with your Python environment activated
python models/download_models.py
```

---

## Model Sources (Direct Links)
- **Face Landmarker:**  
  `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`
- **BlazeFace:**  
  `https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.task`
- **OpenCLIP:**  
  Model `ViT-B-32` with `openai` pretrained tag via HuggingFace Hub (`timm/vit_base_patch32_clip_224.openai`).
