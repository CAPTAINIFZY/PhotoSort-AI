# PhotoSort AI

> **AI-powered event photo culling** — automatically score, rank, and select
> your best shots using computer vision and machine learning.

---

## Project Structure

```
photosort-ai/
├── backend/                  FastAPI Python service
│   ├── main.py               App instance, CORS, /health endpoint
│   ├── db.py                 SQLite/SQLModel — photos table + init_db()
│   ├── config.py             Loads scoring_weights.json at import time
│   ├── requirements.txt      Python dependencies
│   └── .env.example          Environment variable template
│
├── frontend/                 Next.js 14 + TypeScript + Tailwind CSS
│   ├── app/
│   │   ├── layout.tsx        Root layout (Inter font, dark mode)
│   │   ├── globals.css       Design tokens + Tailwind directives
│   │   └── page.tsx          Health-check landing page
│   ├── .env.local.example    Frontend env template
│   └── package.json
│
├── config/
│   └── scoring_weights.json  Scoring weights for CV pipeline (Phase 2+)
│
├── uploads/originals/        Raw uploaded photos (git-ignored at runtime)
├── processed/thumbnails/     Generated thumbnails (git-ignored at runtime)
├── models/                   ML model cache directory (weights git-ignored)
│   ├── README.md             Model directory guide & download instructions
│   └── download_models.py    Helper script to pre-fetch required weights
│
├── .gitignore
└── README.md
```

---

## Model Weights & GitHub Setup

The machine learning models used by PhotoSort AI (MediaPipe FaceLandmarker, BlazeFace, and OpenCLIP ViT-B-32) total over **1.2 GB**, which exceeds GitHub's 100 MB single-file limit.

To ensure seamless GitHub uploads:
- **Model weights are excluded from Git** via `.gitignore`.
- The [`models/`](models/) directory contains lightweight placeholder and setup files:
  - [`models/README.md`](models/README.md): Documents the models used, sizes, and direct source URLs.
  - [`models/download_models.py`](models/download_models.py): Helper script to download all weights in one command.
- **Automatic Acquisition**: You don't have to download them manually — PhotoSort AI automatically downloads any missing model files when the backend runs its first analysis.
- *(Optional)* To pre-download all weights ahead of time:
  ```bash
  python models/download_models.py
  ```

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| Node.js | ≥ 18 |
| npm | ≥ 9 |

---

## Backend Setup

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure environment variables
cp .env.example .env
# Edit .env with your preferred editor

# 5. Start the development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at **http://localhost:8000**.  
Interactive docs: **http://localhost:8000/docs**

### Backend Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `UPLOAD_DIR` | `uploads/originals` | Where raw uploaded photos are stored |
| `THUMBNAIL_DIR` | `processed/thumbnails` | Where generated thumbnails are stored |
| `MODEL_CACHE_DIR` | `models` | Where ML model weights are cached |
| `DB_PATH` | `photosort.db` | SQLite database file path |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Allowed CORS origin |

---

## Frontend Setup

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install Node dependencies
npm install

# 3. Copy and configure environment variables
cp .env.local.example .env.local
# Edit .env.local if your backend runs on a different port

# 4. Start the development server
npm run dev
```

The UI will be available at **http://localhost:3000**.

### Frontend Environment Variables (`.env.local`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:8000` | FastAPI backend base URL |

---

## Health Check

Once both services are running, open **http://localhost:3000**.  
The landing page will automatically probe `GET /health` and show:

- ✅ **Backend: connected** — API, database, and storage are all healthy.
- ❌ **Backend: disconnected** — The API is unreachable (check uvicorn logs).

You can also call the endpoint directly:

```bash
curl http://localhost:8000/health
# → {"status":"ok","db":true,"storage":true}
```

---

## Scoring Weights & Rationales (`config/scoring_weights.json`)

These weights are consumed by the scoring engine (`ai/scoring.py`) to calculate the composite 0–100 score and recommendation:

| Key | Value | Weight Rationale |
|---|---|---|
| `sharpness` | 0.25 | **Highest raw weight**: Focus cannot be recovered in post-processing; blurry/soft images immediately degrade client delivery quality. |
| `exposure` | 0.15 | **Moderate weight**: Modern camera sensors allow moderate highlight/shadow recovery, though severe clipping is still penalized. |
| `face_quality` | 0.20 | **High weight for event/portrait**: Face clarity and open eyes distinguish memorable captures from unusable throwaways. |
| `composition` | 0.20 | **Key aesthetic weight**: Rewards rule-of-thirds alignment, appropriate subject sizing, and head room over poorly framed shots. |
| `uniqueness` | 0.20 | **Diversity weight**: Promotes distinct visual moments while de-prioritizing repetitive burst frames. |
| `blur_penalty` | 0.30 | **Direct deduction**: Penalizes confirmed motion/lens blur to ensure blurry photos never default to "keep". |
| `closed_eye_penalty` | 0.20 | **Direct deduction**: Subtracted when blinks are detected in portrait or candid frames. |
| `duplicate_penalty` | 0.40 | **High deduction**: Applied to near-identical duplicate frames so only the designated AI Pick leads the cluster. |

### Recommendation Thresholds
- **Keep** (Score ≥ 75): High-quality, sharp, well-composed, non-duplicate shots.
- **Review** (50 ≤ Score < 75): Borderline frames, secondary burst members, or shots with minor issues needing photographer discretion.
- **Reject** (Score < 50): Blurry, badly exposed, closed-eye, or corrupt frames.

---

## API Endpoints

### Batch Summary
```http
GET /batches/{batch_id}/summary
```
Returns aggregate counts:
- `total`: Total images in batch
- `best_shots`: Count of photos with `recommendation='keep'`
- `selected_count`: Count of photos with user `status='keep'`
- `categories`: Counts for `people`, `stage`, `candid`, `group`, `other`
- `blur_count`: Count with `blur_detected=true`
- `duplicate_count`: Count with `duplicate=true`
- `closed_eyes_count`: Count with `closed_eyes_detected=true`
- `low_score_count`: Count with `score < review_threshold`
- `failed_count`: Count of files that encountered errors during upload, CV analysis, or scoring

### Paginated & Filtered Gallery
```http
GET /batches/{batch_id}/photos?filter=best_shots&category=people&sort=score_desc&page=1&page_size=60
```
Returns:
```json
{
  "photos": [...],
  "total": 120,
  "page": 1,
  "page_size": 60
}
```
Supported filters: `best_shots`, `blur`, `duplicates`, `closed_eyes`, `low_score`.  
Supported sort modes: `score_desc`, `sharpness_desc`, `similarity` (clusters together, singles last), `newest`, `oldest`.

### Thumbnail & Original Image Serving
- Mounted thumbnails: `GET /thumbnails/{batch_id}/{photo_id}.jpg`
- Thumbnail fallback: `GET /photos/{photo_id}/thumbnail`
- Mounted originals: `GET /originals/{batch_id}/{photo_id}{ext}`
- Original fallback: `GET /photos/{photo_id}/original`

### Photo Detail & Similarity Cluster (Phase 7)
```http
GET /photos/{photo_id}
```
Returns full metadata, scores, recommendation, reasons list, and similarity cluster data:
```json
{
  "id": "p1",
  "filename": "person.jpg",
  "thumbnail_url": "/thumbnails/batch1/p1.jpg",
  "original_url": "/originals/batch1/p1.jpg",
  "category": "people",
  "score": 92.5,
  "cluster": {
    "similarity_group": 101,
    "ai_pick_id": "p1",
    "members": [
      { "id": "p1", "thumbnail_url": "/thumbnails/batch1/p1.jpg", "score": 92.5, "is_ai_pick": true },
      { "id": "p2", "thumbnail_url": "/thumbnails/batch1/p2.jpg", "score": 78.0, "is_ai_pick": false }
    ]
  }
}
```

### Adjacent Navigation (Phase 7)
```http
GET /photos/{photo_id}/adjacent?batch_id={batch_id}&filter=best_shots&sort=score_desc
```
Returns:
```json
{
  "prev_id": "p0",
  "next_id": "p2"
}
```

### Selection & Export Endpoints (Phase 8)

#### Single Photo Status Override
```http
PATCH /photos/{photo_id}/status
Content-Type: application/json

{"status": "keep" | "review" | "reject"}
```
Updates `photos.status` only, preserving AI `score` and `recommendation`.

#### Bulk Photo Status Update
```http
PATCH /batches/{batch_id}/photos/status
Content-Type: application/json

{"photo_ids": ["p1", "p2"], "status": "keep"}
# OR
{"filter": "blur", "status": "reject"}
```
Atomic batch update returning `{"updated_count": int}`.

#### Streaming ZIP Export
```http
POST /batches/{batch_id}/export
Content-Type: application/json

{"photo_ids": ["p1", "p2"]}  # Optional; defaults to all status='keep'
```
Streams original-resolution files in a ZIP download (`photosort_{batch_id}_selected.zip`) with automatic collision resolution and missing-file resilience.

#### Batch Audit CSV Report
```http
GET /batches/{batch_id}/export/report
```
Downloads RFC 4180-compliant CSV (`photosort_{batch_id}_report.csv`) with batch culling summary figures and per-photo score/rationale breakdown.

### Hardening & Rescoring Endpoints (Phase 9)

#### Batch Error Inspection
```http
GET /batches/{batch_id}/errors
```
Returns all logged errors for files that failed upload validation, CV analysis, or scoring:
```json
[
  {
    "photo_id": "p_corrupt",
    "filename": "corrupt_frame.jpg",
    "stage": "cv_analysis",
    "reason": "Image unreadable by OpenCV or corrupt JPEG"
  }
]
```

#### Fast Rescore Batch
```http
POST /batches/{batch_id}/rescore
```
Re-evaluates composition, face, uniqueness, and composite scores across all photos in the batch using the current `scoring_weights.json` configuration without re-running heavy CV or CLIP feature extractors:
```json
{
  "status": "rescored",
  "batch_id": "batch_123",
  "rescored_count": 240
}
```

---

## Known Limitations

1. **Facial Profile Coverage**: MediaPipe FaceLandmarker performs with highest accuracy on frontal and moderate three-quarter facial angles. Extreme profile angles (>75° yaw) or heavy occlusions (>80% of face obscured) fall back gracefully to the neutral 0-face scoring baseline (score = 60.0) rather than failing.
2. **Maximum File Size & Megapixel Limits**: Upload limits are set to 50MB per file (`MAX_FILE_SIZE_BYTES`). Images exceeding this limit or uncompressed TIFF/raw camera formats must be converted to standard JPEG/PNG/WebP before upload.
3. **Rescoring Scope**: The `POST /batches/{batch_id}/rescore` endpoint provides instant sub-second re-scoring by updating weights against cached CV signals and CLIP vectors. It does not re-read raw pixels or re-extract embeddings from scratch. If fundamental computer vision models are replaced, the full analysis pipeline must be triggered.
4. **Local SQLite Concurrency**: The SQLite backend is configured with `check_same_thread=False` and uses `BEGIN IMMEDIATE` transactions to prevent write race conditions during parallel processing. It is optimized for single-photographer workstation use; high multi-tenant concurrent deployments would require migration to PostgreSQL.

---

## How to Re-Run the Demo & Test Suites

### 1. Full 300-Photo Demo Scenario
Executes the complete 300-photo workflow twice (upload → scoring → dashboard → cluster inspection → problem filtering → status overrides → streaming ZIP + CSV export) with detailed timing:
```bash
python backend/demo_scenario.py
```

### 2. Error Handling & Broken Files Audit (Criterion 1)
Tests a deliberately broken batch (corrupt header, 0-byte, wrong extension, truncated file, mid-pipeline corruption) and verifies zero crashes with per-file reporting:
```bash
python backend/test_criterion1_broken_files.py
```

### 3. Weight Tuning & Quality Distribution Benchmark
Verifies the quality separation of tuned weights on a realistic 240-photo dataset (top 30 clean keepers vs. bottom 30 flawed frames):
```bash
python backend/test_phase9_tuning.py
```

### 4. Full Phase Regression Suites
Run any or all phase acceptance suites to verify end-to-end functionality:
```bash
python backend/test_phase5_acceptance.py
python backend/test_phase6_backend.py
python backend/test_phase7_backend.py
python backend/test_phase8_acceptance.py
```

---

## Phases

| Phase | Status | Description |
|---|---|---|
| **1** | ✅ Complete | Project skeleton, DB schema, config loading, health check |
| **2** | ✅ Complete | Image upload endpoint, thumbnail generation, batch management |
| **3** | ✅ Complete | Core CV pipeline — sharpness, exposure, face & eye detection |
| **4** | ✅ Complete | Embeddings (CLIP), category classification, similarity clustering & AI Pick |
| **5** | ✅ Complete | Composition scoring, weighted scoring engine, recommendations ("keep"/"review"/"discard") |
| **6** | ✅ Complete | Culling dashboard, category breakdown, filterable gallery, and photo detail stub |
| **7** | ✅ Complete | Detail inspection view, score breakdown, similarity cluster comparison, and arrow navigation |
| **8** | ✅ Complete | Manual status overrides, bulk action bar, streaming ZIP export, and audit CSV report |
| **9** | ✅ Complete | Error handling audit & fault isolation, weight tuning & rescore endpoint, UI empty/edge states |


