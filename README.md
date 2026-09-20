# PhotoSort AI 📸✨

> **AI-powered event photo culling** — automatically score, de-duplicate, and pick your best shots in seconds using computer vision and machine learning.

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0078D4?style=flat&logo=google)](https://developers.google.com/mediapipe)
[![OpenCLIP](https://img.shields.io/badge/OpenCLIP-FF6F00?style=flat)](https://github.com/mlfoundations/open_clip)

---

## 💡 What Is PhotoSort AI?

After a wedding, concert, birthday party, or corporate event, photographers often return with **hundreds or thousands of photos**. Manually sorting through them ("culling") is exhausting: clicking through 10 nearly identical burst shots to find the one where nobody is blinking, spotting motion blur that looked okay on a camera's small screen, and weeding out poorly lit shots.

**PhotoSort AI does this culling for you automatically.** 
You drag and drop your photo folder into the app, and within moments it:
1. **Grades every image (0–100 score)** based on sharpness, lighting, facial clarity, and composition.
2. **Groups burst duplicates** together and crowns the single sharpest, best-composed photo as the **"AI Pick"**.
3. **Flags issues** like motion blur, closed eyes/blinks, and extreme under/over-exposure.
4. **Gives you a clean gallery** where you can review recommendations, override decisions with 1-click or keyboard shortcuts, and export your keepers in original high resolution as a `.zip` file.

---

## ✨ Key Features

* 🔍 **Smart Focus & Blur Detection**: Uses Laplacian variance and edge frequency analysis to catch motion and lens blur that ruin photos.
* 👁️ **Face Quality & Blink Detection**: Employs Google MediaPipe mesh tracking to detect faces, evaluate expression clarity, and catch blinks.
* 📐 **Rule-of-Thirds Composition**: Automatically analyzes subject placement and headroom relative to golden ratio intersection points.
* 🎯 **Burst De-duplication & AI Picks**: Extracts 512-dimensional CLIP embeddings to cluster visually near-identical frames together, automatically designating the best shot.
* 🏷️ **Automatic Categorization**: Classifies photos into **People**, **Stage**, **Candid**, **Group**, and **Other**.
* ⚡ **Fast & Keyboard-Friendly**: Rapid culling with hotkeys (`K` to Keep, `R` to Review, `X` to Reject) and bulk actions.
* 📦 **One-Click Export**: Downloads only your selected keepers in original quality in a `.zip` archive, plus an audit CSV spreadsheet.
* 🛡️ **Fault-Tolerant Processing**: Corrupt or unreadable files never crash your batch — errors are isolated and reported cleanly per-file.

---

## 🚀 Quick Start Guide

You will need **two terminal windows** open: one for the backend (the processing engine) and one for the frontend (the web interface).

### Prerequisites
* **Python** ≥ 3.11
* **Node.js** ≥ 18 & **npm**

---

### Step 1: Start the Backend (The Engine)

Open your first terminal window:

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a Python virtual environment
python -m venv .venv

# On Windows (PowerShell / Command Prompt):
.venv\Scripts\activate

# On Mac / Linux:
source .venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Start the backend server
uvicorn main:app --reload --port 8000
```
> The backend will start on **`http://localhost:8000`**.  
> You can visit **`http://localhost:8000/docs`** to see interactive API documentation.

---

### Step 2: Start the Frontend (The Web Interface)

Open a **second terminal window**:

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install Node packages
npm install

# 3. Start the Next.js development server
npm run dev
```
> The website will start on **`http://localhost:3000`**.

---

### Step 3: Open in Your Browser

Open your web browser and go to:  
👉 **[http://localhost:3000](http://localhost:3000)**

If both services are running, you will see a green **"Backend: connected"** badge on the home page!

---

## 📖 How to Use It (Step-by-Step)

1. **Upload Your Batch**:
   * Click **"Start Culling"** on the home page.
   * Drag and drop a folder of photos (JPEG, PNG, WebP) and click **"Analyze Photos"**.
2. **Watch the Live Analysis**:
   * Watch the real-time progress bar, checklist (sharpness, exposure, faces, eyes, similarity), and dynamic thumbnail preview strip.
3. **Explore the Culling Dashboard**:
   * Review top stats: Total Photos, Best Shots, Blurry Shots, Blinks, and Duplicate Frames.
   * Filter the gallery by category (**People**, **Stage**, **Candid**, **Group**) or issue filters (**Blur**, **Closed Eyes**, **Duplicates**).
4. **Compare Sibling Shots**:
   * Click any photo with a **"Similar"** tag to enter the Detail View.
   * See all photos from that burst side-by-side with the designated **AI Pick** highlighted.
5. **Make Selections & Export**:
   * Toggle **Keep (✓)**, **Review (?)**, or **Reject (✕)** directly on cards or use keyboard shortcuts (**K / R / X**).
   * Click **"Download Selected (ZIP)"** to get your final curated photos in original resolution.
   * *(Optional)* Click **"Download Report (CSV)"** for an audit spreadsheet of all scores and reasons.

---

## 🧠 Model Weights & GitHub Setup

The machine learning models used by PhotoSort AI (MediaPipe FaceLandmarker, BlazeFace, and OpenCLIP ViT-B-32) total over **1.2 GB**, which exceeds GitHub's 100 MB single-file upload limit.

To keep the repository fast and lightweight:
* **Model weights are excluded from Git** via `.gitignore`.
* The [`models/`](models/) directory contains lightweight placeholder and setup files:
  * [`models/README.md`](models/README.md): Documents the models used, sizes, and direct source URLs.
  * [`models/download_models.py`](models/download_models.py): Helper script to download all weights in one command.
* **Automatic Acquisition**: You do not have to download them manually — PhotoSort AI automatically downloads any missing model files when the backend runs its first analysis.
* *(Optional)* To pre-download all weights ahead of time:
  ```bash
  python models/download_models.py
  ```

---

## ⚖️ Scoring Weights & Rationales (`config/scoring_weights.json`)

Scores (0–100) are calculated dynamically using configurable weights:

| Metric | Weight | Rationale |
|---|---|---|
| **Sharpness** | `0.25` | **Highest priority**: Focus cannot be recovered in post-processing; soft photos immediately look amateur. |
| **Exposure** | `0.15` | **Moderate priority**: Modern sensors allow highlight/shadow recovery, but extreme clipping is penalized. |
| **Face Quality** | `0.20` | **High priority**: Clear facial expressions and open eyes distinguish keepers from throwaways. |
| **Composition** | `0.20` | **Aesthetic priority**: Rewards rule-of-thirds alignment, appropriate subject sizing, and head room. |
| **Uniqueness** | `0.20` | **Diversity priority**: Rewards distinct moments while de-prioritizing repetitive burst duplicates. |

### Deductions & Penalties
* **Blur Penalty** (`0.30`): Subtracted directly when motion blur or lens blur is confirmed.
* **Closed-Eye Penalty** (`0.20`): Subtracted when blinks are detected in portraits or candids.
* **Duplicate Penalty** (`0.40`): Applied to secondary burst frames so only the primary AI Pick leads the cluster.

### Recommendation Thresholds
* **Keep** (Score ≥ 75): High-quality, sharp, well-composed, non-duplicate shots.
* **Review** (50 ≤ Score < 75): Borderline frames, secondary burst members, or shots needing photographer discretion.
* **Reject** (Score < 50): Blurry, badly exposed, closed-eye, or corrupt frames.

---

## 📁 Project Structure

```
PhotoSort AI/
├── backend/                  FastAPI Python service
│   ├── ai/                   Computer vision & ML modules
│   │   ├── blur.py           Laplacian & frequency sharpness estimation
│   │   ├── exposure.py       Brightness & shadow/highlight clipping analysis
│   │   ├── faces.py          MediaPipe face detection & bounding boxes
│   │   ├── eyes.py           MediaPipe eye-mesh blink detection
│   │   ├── embeddings.py     OpenCLIP 512-dim feature extraction
│   │   ├── classify.py       Zero-shot event category classification
│   │   ├── similarity.py     Cosine similarity burst clustering & AI Pick
│   │   ├── composition.py    Rule-of-thirds & subject sizing analysis
│   │   └── scoring.py        Weighted composite scoring & rationale engine
│   ├── routers/              API routes (upload, batches, analysis, photos, clusters)
│   ├── workers/              Background worker job runner & queue
│   ├── db.py                 SQLite / SQLModel database schema & helpers
│   ├── main.py               FastAPI application entry point
│   └── requirements.txt      Python dependencies
│
├── frontend/                 Next.js 14 Web Application
│   ├── app/                  App router pages (home, upload, analyzing, dashboard, photo)
│   ├── components/           UI components (Gallery, PhotoCard, FilterBar, ExportBar)
│   ├── lib/                  Typed API client (api.ts)
│   └── package.json          Node.js dependencies
│
├── config/
│   └── scoring_weights.json  Configurable scoring weights and thresholds
│
├── models/                   Model cache directory (weights git-ignored)
│   ├── README.md             Model guide and direct download links
│   └── download_models.py    One-command model downloader script
│
├── uploads/originals/        Original uploaded images (git-ignored)
├── processed/thumbnails/     Generated 480px thumbnails (git-ignored)
│
├── .gitignore
└── README.md
```

---

## 🧪 Running Automated Tests & Benchmark Demo

PhotoSort AI comes with a comprehensive suite of verification tests:

```bash
# 1. Run the full 300-photo demo scenario (twice, timed)
python backend/demo_scenario.py

# 2. Run broken files & error handling audit (tests corrupt, 0-byte, wrong extension)
python backend/test_criterion1_broken_files.py

# 3. Run weight tuning & quality separation benchmark (240 realistic photos)
python backend/test_phase9_tuning.py

# 4. Run Phase 5-8 regression suites
python backend/test_phase5_acceptance.py
python backend/test_phase6_backend.py
python backend/test_phase7_backend.py
python backend/test_phase8_acceptance.py
```

---

## 🛠️ Known Limitations

1. **Facial Profile Coverage**: MediaPipe FaceLandmarker performs with highest accuracy on frontal and moderate three-quarter facial angles. Extreme profile angles (>75° yaw) or heavy occlusions (>80% of face obscured) fall back gracefully to the neutral 0-face scoring baseline (score = 60.0) rather than failing.
2. **Maximum File Size**: Upload limits default to 50MB per file. High-resolution camera RAW files should be exported to JPEG, PNG, or WebP before upload.
3. **Local SQLite Concurrency**: SQLite transactions use `WAL` mode and `BEGIN IMMEDIATE` to prevent race conditions during parallel processing. It is optimized for single-workstation use.

---

## 📜 License

Distributed under the MIT License. See `LICENSE` for more information.
