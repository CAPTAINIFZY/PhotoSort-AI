"use client";

import { useState } from "react";
import Link from "next/link";
import { BatchPhotoItem, getThumbnailUrl, updatePhotoStatus } from "@/lib/api";

interface PhotoCardProps {
  photo: BatchPhotoItem;
  filterContext?: string;
  onStatusChange?: (photoId: string, newStatus: "keep" | "review" | "reject") => void;
}

export default function PhotoCard({
  photo,
  filterContext,
  onStatusChange,
}: PhotoCardProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [status, setStatus] = useState<string>(photo.status || "review");
  const [isUpdating, setIsUpdating] = useState(false);

  // Score styling
  const score = photo.score !== null ? Math.round(photo.score) : null;
  let scoreBadgeClass = "bg-zinc-800/80 text-zinc-400 border-zinc-700";
  if (score !== null) {
    if (score >= 75) {
      scoreBadgeClass = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-emerald-500/10";
    } else if (score >= 50) {
      scoreBadgeClass = "bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-amber-500/10";
    } else {
      scoreBadgeClass = "bg-rose-500/20 text-rose-300 border-rose-500/40 shadow-rose-500/10";
    }
  }

  const isAiPick = (photo.similarity_group !== null && !photo.duplicate) || photo.recommendation === "keep";
  const thumbnailUrl = getThumbnailUrl(photo.thumbnail_url);
  const detailHref = filterContext
    ? `/photo/${photo.id}?${filterContext}`
    : `/photo/${photo.id}`;

  const handleStatusClick = async (
    e: React.MouseEvent,
    newStatus: "keep" | "review" | "reject"
  ) => {
    e.preventDefault();
    e.stopPropagation();
    if (newStatus === status || isUpdating) return;

    const prev = status;
    setStatus(newStatus);
    setIsUpdating(true);

    try {
      await updatePhotoStatus(photo.id, newStatus);
      if (onStatusChange) {
        onStatusChange(photo.id, newStatus);
      }
    } catch (err: unknown) {
      setStatus(prev);
      alert(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <Link
      href={detailHref}
      className="group relative flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-card)] transition-all duration-300 hover:-translate-y-1 hover:border-indigo-500/50 hover:shadow-[0_8px_25px_rgba(0,0,0,0.5)] focus:outline-none focus:ring-2 focus:ring-indigo-500"
    >
      {/* Thumbnail Aspect Box */}
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-zinc-950">
        {!imageLoaded && !imageError && (
          <div className="absolute inset-0 flex items-center justify-center bg-zinc-900/60 animate-pulse">
            <span className="text-zinc-600 text-xs">Loading...</span>
          </div>
        )}

        {imageError ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-900 p-2 text-center text-xs text-zinc-500">
            <svg
              className="h-8 w-8 text-zinc-600 mb-1"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
            <span className="truncate max-w-[120px]">{photo.filename}</span>
          </div>
        ) : (
          <img
            src={thumbnailUrl}
            alt={photo.filename}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={`h-full w-full object-cover transition-transform duration-500 group-hover:scale-105 ${
              imageLoaded ? "opacity-100" : "opacity-0"
            }`}
          />
        )}

        {/* Gradient Overlay for badges readability */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-zinc-950/80 via-transparent to-zinc-950/40" />

        {/* Top Badges */}
        <div className="absolute top-2 left-2 right-2 flex items-center justify-between gap-1 pointer-events-none">
          {/* Score Badge */}
          <span
            className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold backdrop-blur-md shadow-sm ${scoreBadgeClass}`}
          >
            {score !== null ? `${score}` : "—"}
          </span>

          {/* AI Pick Indicator */}
          {isAiPick && (
            <span className="flex items-center gap-1 rounded-md border border-indigo-400/40 bg-indigo-950/80 px-2 py-0.5 text-[11px] font-bold text-indigo-300 backdrop-blur-md shadow-sm">
              ★ AI PICK
            </span>
          )}
        </div>

        {/* Warning Badges (Bottom of image) */}
        <div className="absolute bottom-2 left-2 right-2 flex flex-wrap gap-1 pointer-events-none">
          {photo.blur_detected && (
            <span className="rounded bg-red-950/90 border border-red-500/40 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-red-300 backdrop-blur-md">
              BLUR
            </span>
          )}
          {photo.closed_eyes_detected && (
            <span className="rounded bg-amber-950/90 border border-amber-500/40 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-300 backdrop-blur-md">
              CLOSED EYES
            </span>
          )}
          {photo.duplicate && (
            <span className="rounded bg-zinc-900/90 border border-zinc-700/60 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-zinc-300 backdrop-blur-md">
              SIMILAR
            </span>
          )}
        </div>
      </div>

      {/* Meta Footer */}
      <div className="flex flex-col gap-2 p-2.5 bg-[var(--bg-card)]">
        <div className="flex items-center justify-between gap-2">
          <p
            title={photo.filename}
            className="truncate text-xs font-medium text-[var(--text-primary)] group-hover:text-indigo-300 transition-colors"
          >
            {photo.filename}
          </p>
          {photo.category && (
            <span className="shrink-0 rounded-full border border-zinc-700 bg-zinc-800/80 px-2 py-0.2 text-[10px] uppercase font-semibold tracking-wider text-zinc-400">
              {photo.category}
            </span>
          )}
        </div>

        {/* Workflow Status Toggle Control */}
        <div className="flex items-center justify-between border-t border-[var(--border)]/60 pt-2">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-semibold">
            Status:
          </span>

          <div className="flex items-center gap-1 rounded-lg bg-zinc-900/90 p-0.5 border border-zinc-800">
            {/* Keep Button */}
            <button
              onClick={(e) => handleStatusClick(e, "keep")}
              title="Mark as Keep (Export candidate)"
              className={`rounded px-2 py-0.5 text-[10px] font-bold transition-all ${
                status === "keep"
                  ? "bg-emerald-500 text-white shadow-sm"
                  : "text-zinc-400 hover:text-emerald-300"
              }`}
            >
              ✓ Keep
            </button>

            {/* Review Button */}
            <button
              onClick={(e) => handleStatusClick(e, "review")}
              title="Mark for Review"
              className={`rounded px-2 py-0.5 text-[10px] font-bold transition-all ${
                status === "review"
                  ? "bg-amber-500 text-black shadow-sm"
                  : "text-zinc-400 hover:text-amber-300"
              }`}
            >
              Review
            </button>

            {/* Reject Button */}
            <button
              onClick={(e) => handleStatusClick(e, "reject")}
              title="Mark as Reject"
              className={`rounded px-2 py-0.5 text-[10px] font-bold transition-all ${
                status === "reject"
                  ? "bg-rose-500 text-white shadow-sm"
                  : "text-zinc-400 hover:text-rose-300"
              }`}
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    </Link>
  );
}
