"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BatchPhotoItem,
  BatchPhotosResponse,
  getBatchPhotos,
  bulkUpdateStatus,
} from "@/lib/api";
import PhotoCard from "./PhotoCard";

interface GalleryProps {
  batchId: string;
  onTotalLoaded?: (total: number) => void;
  onStatusChange?: () => void;
}

export default function Gallery({
  batchId,
  onTotalLoaded,
  onStatusChange,
}: GalleryProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const galleryRef = useRef<HTMLDivElement>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<BatchPhotosResponse | null>(null);
  const [isBulkUpdating, setIsBulkUpdating] = useState(false);

  const filter = searchParams.get("filter") || undefined;
  const category = searchParams.get("category") || undefined;
  const status = searchParams.get("status") || undefined;
  const sort = searchParams.get("sort") || "score_desc";
  const page = parseInt(searchParams.get("page") || "1", 10);
  const pageSize = 60;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getBatchPhotos(batchId, {
      filter,
      category,
      status,
      sort,
      page,
      page_size: pageSize,
    })
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
          if (onTotalLoaded) {
            onTotalLoaded(res.total);
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load photos");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [batchId, filter, category, status, sort, page, onTotalLoaded]);

  const goToPage = (newPage: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(newPage));
    router.push(`${pathname}?${params.toString()}`, { scroll: false });

    // Smooth scroll to top of gallery
    if (galleryRef.current) {
      galleryRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const handleBulkAction = async (targetStatus: "keep" | "review" | "reject") => {
    if (!data || data.photos.length === 0 || isBulkUpdating) return;
    const photoIds = data.photos.map((p) => p.id);
    setIsBulkUpdating(true);

    try {
      await bulkUpdateStatus(batchId, { photoIds, status: targetStatus });
      // Optimistically update visible items
      setData({
        ...data,
        photos: data.photos.map((p) => ({ ...p, status: targetStatus })),
      });
      if (onStatusChange) {
        onStatusChange();
      }
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Bulk status update failed");
    } finally {
      setIsBulkUpdating(false);
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <div ref={galleryRef} className="flex flex-col gap-5">
      {/* Error state */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-center text-sm text-red-300">
          <p className="font-semibold">Unable to load photos</p>
          <p className="mt-1 text-xs text-red-400/80">{error}</p>
          <button
            onClick={() => {
              setError(null);
              setLoading(true);
              getBatchPhotos(batchId, { filter, category, status, sort, page, page_size: pageSize })
                .then(setData)
                .catch((e) => setError(e.message))
                .finally(() => setLoading(false));
            }}
            className="mt-3 rounded-lg bg-red-800/60 px-3 py-1 text-xs font-medium text-white hover:bg-red-700"
          >
            Try Again
          </button>
        </div>
      )}

      {/* Loading Skeletons */}
      {loading && !data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {Array.from({ length: 18 }).map((_, i) => (
            <div
              key={i}
              className="flex flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-card)] animate-pulse"
            >
              <div className="aspect-[4/3] w-full bg-zinc-800/50" />
              <div className="p-3 space-y-2">
                <div className="h-3.5 w-3/4 rounded bg-zinc-800/60" />
                <div className="h-2.5 w-1/2 rounded bg-zinc-800/40" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && data && data.photos.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] p-12 text-center bg-[var(--bg-card)]/40">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-zinc-800/80 text-zinc-400 mb-4 border border-zinc-700/60">
            <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
          </div>
          <h3 className="text-base font-bold text-[var(--text-primary)]">
            {filter || category || status
              ? "No photos match this filter"
              : "No photos in this batch"}
          </h3>
          <p className="mt-1.5 max-w-sm text-xs text-[var(--text-muted)]">
            {filter || category || status
              ? "None of the photos in this batch match the currently selected criteria. Try adjusting or clearing your filters."
              : "No photos have been uploaded or processed in this batch yet."}
          </p>
          {(filter || category || status) && (
            <button
              onClick={() => router.push(pathname, { scroll: false })}
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-indigo-600/20 hover:bg-indigo-500 transition-all"
            >
              <span>↺</span>
              <span>Clear All Filters</span>
            </button>
          )}
        </div>
      )}

      {/* Bulk Action Toolbar */}
      {!loading && data && data.photos.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]/80 p-3 backdrop-blur-sm">
          <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <span className="font-semibold text-[var(--text-primary)]">
              {data.photos.length}
            </span>{" "}
            photos visible on this page:
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => handleBulkAction("keep")}
              disabled={isBulkUpdating}
              className="rounded-lg border border-emerald-500/40 bg-emerald-950/40 px-2.5 py-1 text-xs font-semibold text-emerald-300 hover:bg-emerald-900/60 disabled:opacity-40 transition-colors"
            >
              ✓ Mark All Visible as Keep
            </button>
            <button
              onClick={() => handleBulkAction("review")}
              disabled={isBulkUpdating}
              className="rounded-lg border border-amber-500/40 bg-amber-950/40 px-2.5 py-1 text-xs font-semibold text-amber-300 hover:bg-amber-900/60 disabled:opacity-40 transition-colors"
            >
              Mark as Review
            </button>
            <button
              onClick={() => handleBulkAction("reject")}
              disabled={isBulkUpdating}
              className="rounded-lg border border-rose-500/40 bg-rose-950/40 px-2.5 py-1 text-xs font-semibold text-rose-300 hover:bg-rose-900/60 disabled:opacity-40 transition-colors"
            >
              ✕ Reject All Visible
            </button>
          </div>
        </div>
      )}

      {/* Photo Grid */}
      {data && data.photos.length > 0 && (() => {
        const contextParams = new URLSearchParams();
        if (batchId) contextParams.set("batchId", batchId);
        if (filter) contextParams.set("filter", filter);
        if (category) contextParams.set("category", category);
        if (status) contextParams.set("status", status);
        if (sort && sort !== "score_desc") contextParams.set("sort", sort);
        if (page > 1) contextParams.set("page", String(page));
        const filterContext = contextParams.toString();

        return (
          <div
            className={`grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 transition-opacity duration-200 ${
              loading ? "opacity-50 pointer-events-none" : "opacity-100"
            }`}
          >
            {data.photos.map((photo) => (
              <PhotoCard
                key={photo.id}
                photo={photo}
                filterContext={filterContext}
                onStatusChange={() => {
                  if (onStatusChange) {
                    onStatusChange();
                  }
                }}
              />
            ))}
          </div>
        );
      })()}

      {/* Pagination Bar */}
      {data && totalPages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[var(--border)] pt-4">
          <p className="text-xs text-[var(--text-muted)]">
            Showing photos{" "}
            <span className="font-medium text-[var(--text-primary)]">
              {(page - 1) * pageSize + 1}
            </span>{" "}
            to{" "}
            <span className="font-medium text-[var(--text-primary)]">
              {Math.min(page * pageSize, data.total)}
            </span>{" "}
            of{" "}
            <span className="font-medium text-[var(--text-primary)]">
              {data.total}
            </span>
          </p>

          <div className="flex items-center gap-2">
            <button
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1}
              className="rounded-lg border border-[var(--border)] bg-zinc-900 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:border-zinc-600 disabled:opacity-40 disabled:hover:border-[var(--border)]"
            >
              Previous
            </button>

            <span className="px-2 text-xs text-[var(--text-muted)]">
              Page {page} of {totalPages}
            </span>

            <button
              onClick={() => goToPage(page + 1)}
              disabled={page >= totalPages}
              className="rounded-lg border border-[var(--border)] bg-zinc-900 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:border-zinc-600 disabled:opacity-40 disabled:hover:border-[var(--border)]"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
