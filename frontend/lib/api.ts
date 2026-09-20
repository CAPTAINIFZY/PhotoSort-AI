/**
 * lib/api.ts — PhotoSort AI API client
 *
 * Provides typed wrappers around every backend endpoint consumed by the
 * frontend. All functions read NEXT_PUBLIC_BACKEND_URL so there are no
 * hardcoded hostnames anywhere.
 */

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// ── Shared types ──────────────────────────────────────────────────────────────

export interface RejectedFile {
  filename: string;
  reason: string;
}

export interface AcceptedFile {
  photo_id: string;
  filename: string;
}

export interface UploadResponse {
  batch_id: string;
  accepted_count: number;
  rejected_count: number;
  accepted: AcceptedFile[];
  rejected: RejectedFile[];
}

export interface Photo {
  id: string;
  filename: string;
  batch_id: string | null;
  category: string | null;
  score: number | null;
  sharpness_score: number | null;
  exposure_score: number | null;
  composition_score: number | null;
  face_score: number | null;
  uniqueness_score: number | null;
  mean_brightness: number | null;
  clipped_shadows_pct: number | null;
  clipped_highlights_pct: number | null;
  possible_closed_eyes_count: number | null;
  blur_detected: boolean | null;
  closed_eyes_detected: boolean | null;
  face_count: number | null;
  duplicate: boolean | null;
  similarity_group: number | null;
  recommendation: string | null;
  reasons: string | null;
  status: string | null;
  created_at: string | null;
}

export interface ClusterMember {
  id: string;
  thumbnail_url: string;
  score: number | null;
  is_ai_pick: boolean;
}

export interface PhotoCluster {
  similarity_group: number;
  ai_pick_id: string;
  members: ClusterMember[];
}

export interface PhotoDetail extends Photo {
  thumbnail_url: string;
  original_url: string;
  reasons: string[] | null;
  face_bboxes: Array<{ bbox: [number, number, number, number]; confidence?: number }> | null;
  cluster: PhotoCluster | null;
}

export interface AdjacentPhotosResponse {
  prev_id: string | null;
  next_id: string | null;
}

export interface AdjacentPhotosQuery {
  batch_id?: string;
  category?: string;
  filter?: string;
  status?: string;
  sort?: string;
}

export interface BatchStatus {
  batch_id:    string;
  status:      "pending" | "running" | "completed" | "failed" | null;
  total:       number;
  processed:   number;
  failed:      number;
  started_at:  string | null;
  finished_at: string | null;
}

// ── Phase 6 Dashboard & Gallery Types ─────────────────────────────────────────

export interface CategoryBreakdown {
  people: number;
  stage: number;
  candid: number;
  group: number;
  other: number;
}

export interface BatchErrorItem {
  photo_id?: string | null;
  filename: string;
  stage: string;
  reason: string;
}

export interface BatchSummary {
  total: number;
  best_shots: number;
  selected_count?: number;
  categories: CategoryBreakdown;
  blur_count: number;
  duplicate_count: number;
  closed_eyes_count: number;
  low_score_count: number;
  failed_count?: number;
}

export interface BatchPhotoItem {
  id: string;
  filename: string;
  thumbnail_url: string;
  category: string | null;
  score: number | null;
  blur_detected: boolean | null;
  closed_eyes_detected: boolean | null;
  duplicate: boolean | null;
  similarity_group: number | null;
  recommendation: "keep" | "review" | "reject" | null;
  status: string | null;
}

export interface BatchPhotosResponse {
  photos: BatchPhotoItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface BatchPhotosQuery {
  category?: string;
  filter?: "best_shots" | "blur" | "duplicates" | "closed_eyes" | "low_score" | string;
  status?: "keep" | "review" | "reject" | string;
  sort?: "score_desc" | "newest" | "oldest" | "similarity" | "sharpness_desc" | string;
  page?: number;
  page_size?: number;
}

/**
 * Helper to build an absolute URL for a thumbnail image.
 */
export function getThumbnailUrl(pathOrUrl: string): string {
  if (!pathOrUrl) return "";
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  const cleanPath = pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${BACKEND_URL}${cleanPath}`;
}

// ── uploadBatch ───────────────────────────────────────────────────────────────

export function uploadBatch(
  files: File[],
  onProgress?: (pct: number) => void
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file);
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BACKEND_URL}/upload`);

    if (onProgress) {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
    }

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadResponse);
        } catch {
          reject(new Error("Invalid JSON response from server"));
        }
      } else {
        let detail = `HTTP ${xhr.status}`;
        try {
          const body = JSON.parse(xhr.responseText);
          if (body?.detail) detail = body.detail;
        } catch { /* ignore */ }
        reject(new Error(detail));
      }
    });

    xhr.addEventListener("error",   () => reject(new Error("Network error — check your connection")));
    xhr.addEventListener("timeout", () => reject(new Error("Request timed out")));

    xhr.timeout = 10 * 60 * 1000;
    xhr.send(form);
  });
}

// ── getBatchSummary ───────────────────────────────────────────────────────────

export async function getBatchSummary(batchId: string): Promise<BatchSummary> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/summary`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchSummary>;
}

// ── getBatchPhotos ────────────────────────────────────────────────────────────

export async function getBatchPhotos(
  batchId: string,
  query?: BatchPhotosQuery
): Promise<BatchPhotosResponse> {
  const url = new URL(`${BACKEND_URL}/batches/${batchId}/photos`);
  if (query) {
    if (query.category)  url.searchParams.set("category", query.category);
    if (query.filter)    url.searchParams.set("filter", query.filter);
    if (query.status)    url.searchParams.set("status", query.status);
    if (query.sort)      url.searchParams.set("sort", query.sort);
    if (query.page)      url.searchParams.set("page", String(query.page));
    if (query.page_size) url.searchParams.set("page_size", String(query.page_size));
  }
  const res = await fetch(url.toString(), {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchPhotosResponse>;
}

// ── getPhotoDetail ────────────────────────────────────────────────────────────

export async function getPhotoDetail(photoId: string): Promise<PhotoDetail> {
  const res = await fetch(`${BACKEND_URL}/photos/${photoId}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<PhotoDetail>;
}

// ── getAdjacentPhoto ──────────────────────────────────────────────────────────

export async function getAdjacentPhoto(
  photoId: string,
  query?: AdjacentPhotosQuery
): Promise<AdjacentPhotosResponse> {
  const url = new URL(`${BACKEND_URL}/photos/${photoId}/adjacent`);
  if (query) {
    if (query.batch_id) url.searchParams.set("batch_id", query.batch_id);
    if (query.category) url.searchParams.set("category", query.category);
    if (query.filter)   url.searchParams.set("filter", query.filter);
    if (query.status)   url.searchParams.set("status", query.status);
    if (query.sort)     url.searchParams.set("sort", query.sort);
  }
  const res = await fetch(url.toString(), {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<AdjacentPhotosResponse>;
}

export const getMediaUrl = getThumbnailUrl;

// ── startAnalysis ─────────────────────────────────────────────────────────────

export async function startAnalysis(
  batchId: string
): Promise<{ status: string; batch_id: string; total: number }> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/analyze`, {
    method: "POST",
    cache:  "no-store",
  });
  if (res.status === 409) {
    const body = await res.json().catch(() => ({}));
    return { status: "already_running", batch_id: batchId, total: 0, ...body };
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// ── getBatchStatus ────────────────────────────────────────────────────────────

export async function getBatchStatus(batchId: string): Promise<BatchStatus> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/status`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchStatus>;
}

// ── Phase 8 Status Override & Export APIs ──────────────────────────────────────

export async function updatePhotoStatus(
  photoId: string,
  status: "keep" | "review" | "reject"
): Promise<PhotoDetail> {
  const res = await fetch(`${BACKEND_URL}/photos/${photoId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<PhotoDetail>;
}

export async function bulkUpdateStatus(
  batchId: string,
  options: {
    photoIds?: string[];
    status: "keep" | "review" | "reject";
    filter?: string;
    category?: string;
  }
): Promise<{ updated_count: number }> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/photos/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      photo_ids: options.photoIds,
      status: options.status,
      filter: options.filter,
      category: options.category,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ updated_count: number }>;
}

export async function exportSelectedZip(
  batchId: string,
  photoIds?: string[]
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ photo_ids: photoIds }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `photosort_${batchId}_selected.zip`;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

export async function downloadExportReport(batchId: string): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/export/report`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  const text = await res.text();
  const blob = new Blob([text], { type: "text/csv;charset=utf-8;" });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `photosort_${batchId}_report.csv`;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

export async function getBatchErrors(batchId: string): Promise<BatchErrorItem[]> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/errors`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchErrorItem[]>;
}

export async function rescoreBatch(
  batchId: string
): Promise<{ status: string; batch_id: string; rescored_count: number }> {
  const res = await fetch(`${BACKEND_URL}/batches/${batchId}/rescore`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ status: string; batch_id: string; rescored_count: number }>;
}

