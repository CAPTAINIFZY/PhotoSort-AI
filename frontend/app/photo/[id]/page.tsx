"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  PhotoDetail,
  AdjacentPhotosResponse,
  getPhotoDetail,
  getAdjacentPhoto,
  getThumbnailUrl,
  updatePhotoStatus,
} from "@/lib/api";

function isWarningReason(reason: string): boolean {
  const lower = reason.toLowerCase();
  const warningKeywords = [
    "blur",
    "closed eyes",
    "blink",
    "duplicate",
    "cluster",
    "uneven",
    "harsh",
    "low",
    "penal",
    "poor",
    "dark",
    "clipped",
    "unreadable",
    "corrupt",
    "too small",
    "border",
    "edge",
    "shadow",
    "underexposed",
    "overexposed",
  ];
  return warningKeywords.some((kw) => lower.includes(kw));
}

export default function PhotoDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const { id } = params;
  const router = useRouter();
  const searchParams = useSearchParams();

  const batchIdParam = searchParams.get("batchId") || "";
  const filterParam = searchParams.get("filter") || undefined;
  const categoryParam = searchParams.get("category") || undefined;
  const statusParam = searchParams.get("status") || undefined;
  const sortParam = searchParams.get("sort") || "score_desc";

  const [photo, setPhoto] = useState<PhotoDetail | null>(null);
  const [adjacent, setAdjacent] = useState<AdjacentPhotosResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [originalLoaded, setOriginalLoaded] = useState(false);
  const [originalFailed, setOriginalFailed] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const handleStatusUpdate = useCallback(
    async (newStatus: "keep" | "review" | "reject") => {
      if (!photo || photo.status === newStatus || updatingStatus) return;
      const oldStatus = photo.status;
      setPhoto((prev) => (prev ? { ...prev, status: newStatus } : null));
      setUpdatingStatus(true);
      setStatusError(null);

      try {
        await updatePhotoStatus(photo.id, newStatus);
      } catch (err: unknown) {
        setPhoto((prev) => (prev ? { ...prev, status: oldStatus } : null));
        setStatusError(
          err instanceof Error ? err.message : "Failed to update status"
        );
      } finally {
        setUpdatingStatus(false);
      }
    },
    [photo, updatingStatus]
  );

  // Fetch photo details
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setOriginalLoaded(false);
    setOriginalFailed(false);

    getPhotoDetail(id)
      .then((res) => {
        if (!cancelled) {
          setPhoto(res);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load photo details"
          );
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Fetch adjacent photo IDs
  useEffect(() => {
    let cancelled = false;

    getAdjacentPhoto(id, {
      batch_id: batchIdParam || photo?.batch_id || undefined,
      category: categoryParam,
      filter: filterParam,
      status: statusParam,
      sort: sortParam,
    })
      .then((res) => {
        if (!cancelled) {
          setAdjacent(res);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAdjacent({ prev_id: null, next_id: null });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id, batchIdParam, photo?.batch_id, filterParam, categoryParam, statusParam, sortParam]);

  const effectiveBatchId = batchIdParam || photo?.batch_id || "";

  // Navigation helpers preserving current query params
  const navigateToPhoto = useCallback(
    (targetId: string) => {
      const q = searchParams.toString();
      router.push(q ? `/photo/${targetId}?${q}` : `/photo/${targetId}`);
    },
    [router, searchParams]
  );

  const navigateBackToGallery = useCallback(() => {
    if (effectiveBatchId) {
      const q = searchParams.toString();
      router.push(q ? `/dashboard/${effectiveBatchId}?${q}` : `/dashboard/${effectiveBatchId}`);
    } else {
      router.back();
    }
  }, [effectiveBatchId, router, searchParams]);

  // Keyboard navigation & hotkeys: Left/Right (nav), Escape (back), K/R/X (culling status)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Avoid hijacking input fields
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "ArrowLeft" && adjacent?.prev_id) {
        e.preventDefault();
        navigateToPhoto(adjacent.prev_id);
      } else if (e.key === "ArrowRight" && adjacent?.next_id) {
        e.preventDefault();
        navigateToPhoto(adjacent.next_id);
      } else if (e.key === "Escape") {
        e.preventDefault();
        navigateBackToGallery();
      } else if (e.key === "k" || e.key === "K") {
        e.preventDefault();
        handleStatusUpdate("keep");
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        handleStatusUpdate("review");
      } else if (e.key === "x" || e.key === "X") {
        e.preventDefault();
        handleStatusUpdate("reject");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [adjacent, navigateToPhoto, navigateBackToGallery, handleStatusUpdate]);

  const score = photo?.score !== null && photo?.score !== undefined ? Math.round(photo.score) : null;
  let scoreBadgeClass = "bg-zinc-800 text-zinc-400 border-zinc-700";
  if (score !== null) {
    if (score >= 75) {
      scoreBadgeClass = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
    } else if (score >= 50) {
      scoreBadgeClass = "bg-amber-500/20 text-amber-300 border-amber-500/40";
    } else {
      scoreBadgeClass = "bg-rose-500/20 text-rose-300 border-rose-500/40";
    }
  }

  const recommendationColor =
    photo?.recommendation === "keep"
      ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/40 shadow-emerald-500/10"
      : photo?.recommendation === "review"
      ? "bg-amber-950/70 text-amber-300 border-amber-500/40 shadow-amber-500/10"
      : "bg-rose-950/70 text-rose-300 border-rose-500/40 shadow-rose-500/10";

  const thumbnailSrc = photo?.thumbnail_url
    ? getThumbnailUrl(photo.thumbnail_url)
    : photo?.batch_id
    ? getThumbnailUrl(`/thumbnails/${photo.batch_id}/${photo.id}.jpg`)
    : "";

  const originalSrc = photo?.original_url
    ? getThumbnailUrl(photo.original_url)
    : photo?.batch_id
    ? getThumbnailUrl(`/photos/${photo.id}/original`)
    : "";

  const hasFaces = (photo?.face_count ?? 0) > 0;

  return (
    <main className="relative min-h-dvh overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
      {/* Ambient background blur */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[600px] -translate-x-1/2 rounded-full bg-indigo-600/10 blur-[130px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-10 right-0 h-[400px] w-[400px] rounded-full bg-purple-700/10 blur-[120px]"
      />

      <div className="relative z-10 mx-auto max-w-7xl">
        {/* Top Control Bar */}
        <header className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)]/60 pb-4">
          <div className="flex items-center gap-3">
            <button
              onClick={navigateBackToGallery}
              className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3.5 py-1.5 text-xs font-semibold text-[var(--text-primary)] hover:border-indigo-500/60 hover:text-indigo-300 transition-colors"
            >
              ← Back to Gallery
            </button>

            {photo?.filename && (
              <span className="hidden sm:inline-block max-w-[240px] truncate font-mono text-xs text-[var(--text-muted)]">
                {photo.filename}
              </span>
            )}
          </div>

          {/* Adjacent Navigation Buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => adjacent?.prev_id && navigateToPhoto(adjacent.prev_id)}
              disabled={!adjacent?.prev_id}
              title="Previous photo (Left Arrow)"
              className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-zinc-900 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <span>←</span>
              <span className="hidden sm:inline">Prev</span>
              <kbd className="hidden md:inline rounded bg-zinc-800 px-1 py-0.5 text-[10px] text-zinc-400">
                ←
              </kbd>
            </button>

            <button
              onClick={() => adjacent?.next_id && navigateToPhoto(adjacent.next_id)}
              disabled={!adjacent?.next_id}
              title="Next photo (Right Arrow)"
              className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-zinc-900 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <span className="hidden sm:inline">Next</span>
              <span>→</span>
              <kbd className="hidden md:inline rounded bg-zinc-800 px-1 py-0.5 text-[10px] text-zinc-400">
                →
              </kbd>
            </button>
          </div>
        </header>

        {/* Loading Spinner */}
        {loading && (
          <div className="flex flex-col items-center justify-center p-24 text-center">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-500/20 border-t-indigo-500 mb-4" />
            <p className="text-sm text-[var(--text-muted)]">Loading inspection view…</p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="rounded-2xl border border-red-500/30 bg-red-950/40 p-8 text-center text-sm text-red-300">
            <h2 className="text-xl font-bold">Photo Not Found</h2>
            <p className="mt-2 text-xs text-red-400/80">{error}</p>
            <button
              onClick={navigateBackToGallery}
              className="mt-5 rounded-xl bg-zinc-800 px-4 py-2 text-xs font-semibold text-white hover:bg-zinc-700"
            >
              Return to Gallery
            </button>
          </div>
        )}

        {/* Main Content Layout */}
        {!loading && photo && (
          <div className="flex flex-col gap-8">
            {/* Top Row: Hero Canvas (Left) + Score & Rationale Sidebar (Right) */}
            <div className="grid grid-cols-1 gap-8 lg:grid-cols-12">
              {/* Left Canvas: Large Image Hero */}
              <div className="lg:col-span-7 flex flex-col gap-3">
                <div className="relative overflow-hidden rounded-2xl border border-[var(--border)] bg-zinc-950 shadow-2xl flex items-center justify-center min-h-[420px] max-h-[700px]">
                  {/* Immediate Thumbnail as progressive background */}
                  {thumbnailSrc && (
                    <img
                      src={thumbnailSrc}
                      alt={photo.filename}
                      className={`h-full w-full object-contain transition-opacity duration-500 ${
                        originalLoaded ? "opacity-0 absolute inset-0" : "opacity-100"
                      }`}
                    />
                  )}

                  {/* Lazy-Loaded Full-Resolution Original */}
                  {originalSrc && !originalFailed && (
                    <img
                      src={originalSrc}
                      alt={photo.filename}
                      loading="eager"
                      onLoad={() => setOriginalLoaded(true)}
                      onError={() => setOriginalFailed(true)}
                      className={`h-full w-full object-contain transition-opacity duration-500 ${
                        originalLoaded ? "opacity-100" : "opacity-0 absolute inset-0 pointer-events-none"
                      }`}
                    />
                  )}

                  {/* Resolution & Load status badge */}
                  <div className="absolute bottom-3 right-3 flex items-center gap-2 rounded-lg bg-zinc-950/80 border border-zinc-800/80 px-2.5 py-1 text-[11px] text-zinc-400 backdrop-blur-md">
                    {originalLoaded ? (
                      <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                        Full Resolution
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 text-zinc-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
                        Optimized Preview
                      </span>
                    )}
                  </div>
                </div>

                {/* Filename & Info below canvas */}
                <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-[var(--text-muted)]">
                  <span className="font-mono text-[var(--text-primary)] font-medium truncate max-w-sm">
                    {photo.filename}
                  </span>
                  <div className="flex items-center gap-3">
                    {photo.category && (
                      <span className="rounded-full border border-zinc-700 bg-zinc-800/80 px-2.5 py-0.5 text-[10px] uppercase font-bold tracking-wider text-indigo-300">
                        {photo.category}
                      </span>
                    )}
                    <span className="font-mono text-zinc-500 text-[11px]">
                      ID: {photo.id.slice(0, 10)}...
                    </span>
                  </div>
                </div>
              </div>

              {/* Right Panel: Scores & Rationale */}
              <div className="lg:col-span-5 flex flex-col gap-5">
                {/* Overall Score & Recommendation Card */}
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                      AI Recommendation
                    </span>
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wider ${recommendationColor}`}
                    >
                      {photo.recommendation ?? "Pending"}
                    </span>
                  </div>

                  <div className="mt-4 flex items-baseline justify-between border-t border-[var(--border)]/60 pt-4">
                    <div>
                      <span className="text-xs text-[var(--text-muted)]">Overall Quality Score</span>
                      <p className="text-4xl font-extrabold text-[var(--text-primary)]">
                        {score !== null ? score : "—"}
                        <span className="text-sm font-normal text-[var(--text-muted)]"> / 100</span>
                      </p>
                    </div>

                    <span
                      className={`rounded-xl border px-3 py-1 text-xs font-semibold ${scoreBadgeClass}`}
                    >
                      {score !== null && score >= 75
                        ? "Top Quality"
                        : score !== null && score >= 50
                        ? "Candidate"
                        : "Low Quality"}
                    </span>
                  </div>
                </div>

                {/* Photographer Culling Decision / Manual Override Card */}
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                      Photographer Decision
                    </span>
                    <span className="text-[11px] text-zinc-400">
                      Current:{" "}
                      <span
                        className={`font-semibold uppercase ${
                          photo.status === "keep"
                            ? "text-emerald-400"
                            : photo.status === "reject"
                            ? "text-rose-400"
                            : "text-amber-400"
                        }`}
                      >
                        {photo.status ?? photo.recommendation ?? "review"}
                      </span>
                    </span>
                  </div>

                  <div className="grid grid-cols-3 gap-2">
                    <button
                      onClick={() => handleStatusUpdate("keep")}
                      disabled={updatingStatus}
                      title="Mark as Keep (Press K)"
                      className={`flex items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-all ${
                        photo.status === "keep"
                          ? "border-emerald-500 bg-emerald-950/70 text-emerald-300 shadow-md shadow-emerald-500/20 ring-1 ring-emerald-500"
                          : "border-zinc-800 bg-zinc-900/80 text-zinc-400 hover:border-emerald-500/50 hover:text-emerald-300"
                      }`}
                    >
                      <span>✓</span>
                      <span>Keep</span>
                      <kbd className="hidden sm:inline rounded bg-black/40 px-1 py-0.5 text-[9px] text-zinc-400">
                        K
                      </kbd>
                    </button>

                    <button
                      onClick={() => handleStatusUpdate("review")}
                      disabled={updatingStatus}
                      title="Mark as Review (Press R)"
                      className={`flex items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-all ${
                        photo.status === "review"
                          ? "border-amber-500 bg-amber-950/70 text-amber-300 shadow-md shadow-amber-500/20 ring-1 ring-amber-500"
                          : "border-zinc-800 bg-zinc-900/80 text-zinc-400 hover:border-amber-500/50 hover:text-amber-300"
                      }`}
                    >
                      <span>?</span>
                      <span>Review</span>
                      <kbd className="hidden sm:inline rounded bg-black/40 px-1 py-0.5 text-[9px] text-zinc-400">
                        R
                      </kbd>
                    </button>

                    <button
                      onClick={() => handleStatusUpdate("reject")}
                      disabled={updatingStatus}
                      title="Mark as Reject (Press X)"
                      className={`flex items-center justify-center gap-1.5 rounded-xl border py-2 text-xs font-semibold transition-all ${
                        photo.status === "reject"
                          ? "border-rose-500 bg-rose-950/70 text-rose-300 shadow-md shadow-rose-500/20 ring-1 ring-rose-500"
                          : "border-zinc-800 bg-zinc-900/80 text-zinc-400 hover:border-rose-500/50 hover:text-rose-300"
                      }`}
                    >
                      <span>✕</span>
                      <span>Reject</span>
                      <kbd className="hidden sm:inline rounded bg-black/40 px-1 py-0.5 text-[9px] text-zinc-400">
                        X
                      </kbd>
                    </button>
                  </div>

                  {statusError && (
                    <p className="mt-2 text-[11px] text-rose-400">{statusError}</p>
                  )}
                </div>

                {/* Component Quality Score Bars */}
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-3.5">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    Quality Pillars
                  </h3>

                  {[
                    { label: "Sharpness", val: photo.sharpness_score },
                    { label: "Exposure", val: photo.exposure_score },
                    { label: "Composition", val: photo.composition_score },
                    {
                      label: "Face Quality",
                      val: hasFaces ? photo.face_score : null,
                      note: !hasFaces ? "N/A (No faces detected)" : undefined,
                    },
                    { label: "Uniqueness", val: photo.uniqueness_score },
                  ].map((item) => (
                    <div key={item.label}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[var(--text-muted)]">{item.label}</span>
                        <span className="font-semibold text-[var(--text-primary)]">
                          {item.note
                            ? item.note
                            : item.val !== null && item.val !== undefined
                            ? Math.round(item.val)
                            : "—"}
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            item.note
                              ? "bg-zinc-700 opacity-40"
                              : (item.val ?? 0) >= 75
                              ? "bg-gradient-to-r from-indigo-500 to-emerald-400"
                              : (item.val ?? 0) >= 50
                              ? "bg-gradient-to-r from-indigo-500 to-amber-400"
                              : "bg-rose-500"
                          }`}
                          style={{ width: `${item.note ? 0 : item.val ?? 0}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Rationale Checklist (✓ and ⚠) */}
                {photo.reasons && photo.reasons.length > 0 && (
                  <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">
                      AI Decision Rationale
                    </h3>
                    <ul className="space-y-2">
                      {photo.reasons.map((reason, idx) => {
                        const isWarn = isWarningReason(reason);
                        return (
                          <li
                            key={idx}
                            className={`flex items-start gap-2.5 text-xs rounded-lg p-2 ${
                              isWarn
                                ? "bg-amber-950/20 text-amber-300/90 border border-amber-500/20"
                                : "bg-emerald-950/20 text-emerald-300/90 border border-emerald-500/20"
                            }`}
                          >
                            <span
                              className={`shrink-0 font-bold ${
                                isWarn ? "text-amber-400" : "text-emerald-400"
                              }`}
                            >
                              {isWarn ? "⚠" : "✓"}
                            </span>
                            <span className="leading-relaxed">{reason}</span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>
            </div>

            {/* Bottom Section: Similarity Cluster Comparison (if clustered) */}
            {photo.cluster && photo.cluster.members.length > 0 && (
              <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 shadow-lg">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
                  <div>
                    <h3 className="text-sm font-bold text-[var(--text-primary)] flex items-center gap-2">
                      <span>Similar Frames Cluster</span>
                      <span className="rounded-full bg-indigo-950/80 border border-indigo-500/40 px-2 py-0.5 text-xs text-indigo-300">
                        Group #{photo.cluster.similarity_group}
                      </span>
                    </h3>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">
                      {photo.cluster.members.length} visually similar burst/pose frames evaluated by CLIP.
                    </p>
                  </div>
                </div>

                {/* Horizontal Filmstrip */}
                <div className="flex gap-4 overflow-x-auto pb-2 pt-1">
                  {photo.cluster.members.map((member) => {
                    const isCurrent = member.id === photo.id;
                    const memberScore = member.score !== null ? Math.round(member.score) : "—";
                    const thumbUrl = getThumbnailUrl(member.thumbnail_url);

                    return (
                      <div
                        key={member.id}
                        onClick={() => navigateToPhoto(member.id)}
                        className={`group relative flex-shrink-0 w-36 sm:w-44 cursor-pointer overflow-hidden rounded-xl border bg-zinc-950 transition-all duration-200 ${
                          isCurrent
                            ? "border-indigo-500 ring-2 ring-indigo-500/60 shadow-lg shadow-indigo-500/20"
                            : "border-[var(--border)] hover:border-zinc-500 hover:scale-[1.02]"
                        }`}
                      >
                        {/* Member Thumbnail */}
                        <div className="relative aspect-[4/3] w-full overflow-hidden bg-zinc-900">
                          <img
                            src={thumbUrl}
                            alt={`Cluster member ${member.id}`}
                            className="h-full w-full object-cover"
                          />

                          {/* Gradient */}
                          <div className="absolute inset-0 bg-gradient-to-t from-zinc-950/80 via-transparent to-zinc-950/40 pointer-events-none" />

                          {/* Top Badges */}
                          <div className="absolute top-1.5 left-1.5 right-1.5 flex items-center justify-between gap-1 pointer-events-none">
                            <span className="rounded bg-zinc-900/90 border border-zinc-700 px-1.5 py-0.2 text-[10px] font-bold text-zinc-300 backdrop-blur-md">
                              {memberScore}
                            </span>

                            {member.is_ai_pick && (
                              <span className="rounded bg-indigo-950/90 border border-indigo-400 px-1.5 py-0.2 text-[10px] font-bold text-indigo-300 backdrop-blur-md">
                                ★ AI PICK
                              </span>
                            )}
                          </div>

                          {/* Current Photo Indicator */}
                          {isCurrent && (
                            <div className="absolute bottom-1.5 left-1.5 rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-bold text-white uppercase tracking-wider shadow">
                              Inspecting
                            </div>
                          )}
                        </div>

                        <div className="p-2 text-center text-[10px] text-zinc-400 truncate">
                          {member.id.slice(0, 10)}...
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
