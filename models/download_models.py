"""
download_models.py -- PhotoSort AI Model Downloader Helper
Downloads required ML model weights into the models/ directory if not present.
"""

import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent

MEDIAPIPE_MODELS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    "blaze_face_short_range.tflite": (
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/1/blaze_face_short_range.task"
    ),
}

def download_file(url: str, dest: Path) -> None:
    print(f"Downloading {dest.name} from Google Storage...")
    def _reporthook(block_num, block_size, total_size):
        if total_size > 0:
            pct = min(100, int(block_num * block_size * 100 / total_size))
            sys.stdout.write(f"\r  Progress: {pct}% ({block_num * block_size // 1024} KB / {total_size // 1024} KB)")
            sys.stdout.flush()
    urllib.request.urlretrieve(url, str(dest), reporthook=_reporthook)
    print("\n  Done.")

def main():
    print("=" * 60)
    print("  PhotoSort AI -- Model Weights Downloader")
    print("=" * 60)
    print(f"Target directory: {MODELS_DIR}\n")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Download MediaPipe models
    for filename, url in MEDIAPIPE_MODELS.items():
        dest = MODELS_DIR / filename
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"[OK] {filename} already exists ({dest.stat().st_size // 1024} KB).")
        else:
            download_file(url, dest)

    # 2. Pre-cache OpenCLIP
    print("\nChecking OpenCLIP ViT-B-32 weights...")
    try:
        import open_clip
        print("Pre-warming OpenCLIP model (openai weights)...")
        os.environ["HF_HOME"] = str(MODELS_DIR)
        open_clip.create_model_and_transforms(
            "ViT-B-32",
            pretrained="openai",
            cache_dir=str(MODELS_DIR),
        )
        print("[OK] OpenCLIP weights ready in models/ directory.")
    except ImportError:
        print("[!] open_clip_torch not installed in current environment.")
        print("    Run: pip install open-clip-torch (or pip install -r backend/requirements.txt)")
    except Exception as exc:
        print(f"[!] Warning: OpenCLIP pre-warm encountered an issue: {exc}")
        print("    The backend will retry downloading it automatically on first run.")

    print("\n" + "=" * 60)
    print("  All model setup steps finished successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
