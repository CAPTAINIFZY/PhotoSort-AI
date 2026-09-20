"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import {
  BatchSummary,
  getBatchSummary,
  getBatchErrors,
  BatchErrorItem,
} from "@/lib/api";
import FilterBar from "@/components/FilterBar";
import Gallery from "@/components/Gallery";
import ExportBar from "@/components/ExportBar";

export default function DashboardPage({
  params,
}: {
  params: { batchId: string };
}) {
  const { batchId } = params;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [totalMatching, setTotalMatching] = useState<number | undefined>(undefined);
  const [batchErrors, setBatchErrors] = useState<BatchErrorItem[]>([]);
  const [showErrors, setShowErrors] = useState(false);

  const activeCategory = searchParams.get("category") || "";
  const activeFilter = searchParams.get("filter") || "";

  const refetchSummary = useCallback(() => {
    getBatchSummary(batchId)
      .then((res) => {
        setSummary(res);
        if (res.failed_count && res.failed_count > 0) {
          getBatchErrors(batchId).then(setBatchErrors).catch(() => {});
        }
      })
      .catch(() => {});
  }, [batchId]);

  useEffect(() => {
    let cancelled = false;
    setLoadingSummary(true);
    setSummaryError(null);

    getBatchSummary(batchId)
      .then((res) => {
        if (!cancelled) {
          setSummary(res);
          setLoadingSummary(false);
          if (res.failed_count && res.failed_count > 0) {
            getBatchErrors(batchId).then((errs) => {
              if (!cancelled) setBatchErrors(errs);
            }).catch(() => {});
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSummaryError(
            err instanceof Error ? err.message : "Failed to load summary"
          );
          setLoadingSummary(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [batchId]);

  const toggleFilter = useCallback(
    (filterName: string) => {
      const current = searchParams.get("filter");
      const params = new URLSearchParams(searchParams.toString());
      params.delete("page");

      if (current === filterName) {
        params.delete("filter");
      } else {
        params.set("filter", filterName);
      }
      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const toggleCategory = useCallback(
    (categoryName: string) => {
      const current = searchParams.get("category");
      const params = new URLSearchParams(searchParams.toString());
      params.delete("page");

      if (current === categoryName) {
        params.delete("category");
      } else {
        params.set("category", categoryName);
      }
      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  return (
    <main className="relative min-h-dvh overflow-hidden px-4 py-8 sm:px-6 lg:px-8">
      {/* Ambient backgrounds */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[600px] -translate-x-1/2 rounded-full bg-indigo-600/10 blur-[130px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute top-1/3 right-0 h-[400px] w-[400px] rounded-full bg-purple-700/10 blur-[120px]"
      />

      <div className="relative z-10 mx-auto max-w-7xl">
        {/* Navigation / Header */}
        <header className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)]/60 pb-5">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2.5 group">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 shadow-md shadow-indigo-500/20">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="white"
                  className="h-5 w-5"
                >
                  <path d="M12 9a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 9Z" />
                  <path
                    fillRule="evenodd"
                    d="M9.344 3.071a49.52 49.52 0 0 1 5.312 0c.967.052 1.83.585 2.332 1.39l.821 1.317c.24.383.645.643 1.11.71.386.054.77.113 1.152.177 1.432.239 2.429 1.493 2.429 2.909V18a3 3 0 0 1-3 3h-15a3 3 0 0 1-3-3V9.574c0-1.416.997-2.67 2.429-2.909.382-.064.766-.123 1.151-.178a1.56 1.56 0 0 0 1.11-.71l.822-1.315a2.942 2.942 0 0 1 2.332-1.39ZM6.75 12.75a5.25 5.25 0 1 1 10.5 0 5.25 5.25 0 0 1-10.5 0Zm12-1.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <div>
                <span className="text-base font-bold text-[var(--text-primary)] group-hover:text-indigo-300 transition-colors">
                  PhotoSort AI
                </span>
                <span className="block text-[11px] text-[var(--text-muted)]">
                  Culling &amp; Gallery Dashboard
                </span>
              </div>
            </Link>
          </div>

          <div className="flex items-center gap-3">
            <span className="rounded-full border border-zinc-700/80 bg-zinc-800/80 px-3 py-1 text-xs font-mono text-zinc-300">
              Batch: <span className="text-indigo-400">{batchId.slice(0, 8)}...</span>
            </span>

            <Link
              href="/upload"
              className="rounded-xl border border-indigo-500/40 bg-indigo-950/40 px-3.5 py-1.5 text-xs font-semibold text-indigo-300 hover:bg-indigo-900/60 hover:border-indigo-400 transition-colors"
            >
              + Upload New
            </Link>
          </div>
        </header>

        {/* Error banner */}
        {summaryError && (
          <div className="mb-6 rounded-xl border border-red-500/30 bg-red-950/40 p-4 text-sm text-red-300">
            Failed to load batch summary: {summaryError}
          </div>
        )}

        {/* Processing Failures Warning Banner */}
        {summary && summary.failed_count !== undefined && summary.failed_count > 0 && (
          <div className="mb-6 rounded-2xl border border-amber-500/40 bg-amber-950/30 p-4 backdrop-blur-md">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/20 text-xs font-bold text-amber-400">
                  ⚠
                </span>
                <span className="text-xs font-semibold text-amber-200">
                  {summary.failed_count} file{summary.failed_count > 1 ? "s" : ""} could not be processed during upload or analysis.
                </span>
              </div>
              <button
                onClick={() => setShowErrors(!showErrors)}
                className="rounded-lg border border-amber-500/40 bg-amber-900/40 px-3 py-1 text-xs font-semibold text-amber-300 hover:bg-amber-800/60 transition-colors"
              >
                {showErrors ? "Hide Details" : "View Details"}
              </button>
            </div>

            {showErrors && (
              <div className="mt-3 divide-y divide-amber-500/20 border-t border-amber-500/20 pt-3 text-xs">
                {batchErrors.length > 0 ? (
                  batchErrors.map((err, idx) => (
                    <div key={idx} className="py-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-zinc-300 font-medium">{err.filename}</span>
                        <span className="rounded bg-amber-900/60 border border-amber-600/40 px-1.5 py-0.2 text-[10px] uppercase font-mono text-amber-300">
                          {err.stage}
                        </span>
                      </div>
                      <span className="text-amber-400/90 font-mono text-[11px]">{err.reason}</span>
                    </div>
                  ))
                ) : (
                  <p className="text-zinc-400 py-1">No detailed error logs found.</p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Top Summary Stat Strip */}
        <section className="mb-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {/* Total Photos */}
            <div
              onClick={() => toggleFilter("")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                !activeFilter
                  ? "border-zinc-500 bg-zinc-800/80 ring-1 ring-zinc-500"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-zinc-700"
              }`}
            >
              <p className="text-xs font-medium text-[var(--text-muted)]">Total Photos</p>
              <p className="mt-1 text-2xl font-extrabold text-[var(--text-primary)]">
                {loadingSummary ? "—" : summary?.total ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-zinc-500">In this batch</p>
            </div>

            {/* Best Shots */}
            <div
              onClick={() => toggleFilter("best_shots")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                activeFilter === "best_shots"
                  ? "border-emerald-500 bg-emerald-950/40 ring-1 ring-emerald-500"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-emerald-500/40"
              }`}
            >
              <p className="text-xs font-medium text-emerald-400">★ Best Shots</p>
              <p className="mt-1 text-2xl font-extrabold text-emerald-300">
                {loadingSummary ? "—" : summary?.best_shots ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-emerald-500/80">Recommended Keep</p>
            </div>

            {/* Blur */}
            <div
              onClick={() => toggleFilter("blur")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                activeFilter === "blur"
                  ? "border-red-500 bg-red-950/40 ring-1 ring-red-500"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-red-500/40"
              }`}
            >
              <p className="text-xs font-medium text-red-400">Blur Issues</p>
              <p className="mt-1 text-2xl font-extrabold text-red-300">
                {loadingSummary ? "—" : summary?.blur_count ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-red-500/80">Soft / out of focus</p>
            </div>

            {/* Duplicates */}
            <div
              onClick={() => toggleFilter("duplicates")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                activeFilter === "duplicates"
                  ? "border-indigo-500 bg-indigo-950/40 ring-1 ring-indigo-500"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-indigo-500/40"
              }`}
            >
              <p className="text-xs font-medium text-indigo-400">Similar / Dups</p>
              <p className="mt-1 text-2xl font-extrabold text-indigo-300">
                {loadingSummary ? "—" : summary?.duplicate_count ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-indigo-400/80">Secondary cluster frames</p>
            </div>

            {/* Closed Eyes */}
            <div
              onClick={() => toggleFilter("closed_eyes")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                activeFilter === "closed_eyes"
                  ? "border-amber-500 bg-amber-950/40 ring-1 ring-amber-500"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-amber-500/40"
              }`}
            >
              <p className="text-xs font-medium text-amber-400">Closed Eyes</p>
              <p className="mt-1 text-2xl font-extrabold text-amber-300">
                {loadingSummary ? "—" : summary?.closed_eyes_count ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-amber-500/80">Blinking detected</p>
            </div>

            {/* Low Score */}
            <div
              onClick={() => toggleFilter("low_score")}
              className={`cursor-pointer rounded-xl border p-3.5 backdrop-blur-md transition-all duration-200 ${
                activeFilter === "low_score"
                  ? "border-zinc-400 bg-zinc-800/80 ring-1 ring-zinc-400"
                  : "border-[var(--border)] bg-[var(--bg-card)] hover:border-zinc-600"
              }`}
            >
              <p className="text-xs font-medium text-zinc-400">Low Score</p>
              <p className="mt-1 text-2xl font-extrabold text-zinc-300">
                {loadingSummary ? "—" : summary?.low_score_count ?? 0}
              </p>
              <p className="mt-0.5 text-[10px] text-zinc-500">Below review bar</p>
            </div>
          </div>
        </section>

        {/* Category Breakdown Tiles */}
        <section className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Categories
            </h2>
            {activeCategory && (
              <button
                onClick={() => toggleCategory(activeCategory)}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                Clear category filter
              </button>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5">
            {(
              [
                { id: "people", label: "People", icon: "👤" },
                { id: "stage", label: "Stage", icon: "🎭" },
                { id: "candid", label: "Candid", icon: "📸" },
                { id: "group", label: "Group", icon: "👥" },
                { id: "other", label: "Other", icon: "📁" },
              ] as const
            ).map((cat) => {
              const count = summary?.categories[cat.id] ?? 0;
              const isSelected = activeCategory === cat.id;

              return (
                <button
                  key={cat.id}
                  onClick={() => toggleCategory(cat.id)}
                  className={`flex items-center justify-between rounded-xl border px-3.5 py-2.5 text-left transition-all duration-200 ${
                    isSelected
                      ? "border-indigo-500 bg-indigo-950/60 ring-1 ring-indigo-500"
                      : "border-[var(--border)] bg-[var(--bg-card)] hover:border-zinc-700"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-base">{cat.icon}</span>
                    <span className="text-xs font-medium text-[var(--text-primary)]">
                      {cat.label}
                    </span>
                  </div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      isSelected
                        ? "bg-indigo-600 text-white"
                        : "bg-zinc-800 text-zinc-400"
                    }`}
                  >
                    {loadingSummary ? "—" : count}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* Export & Culling Action Bar */}
        <section className="mb-6">
          <ExportBar
            batchId={batchId}
            selectedCount={summary?.selected_count ?? 0}
            totalCount={summary?.total ?? 0}
          />
        </section>

        {/* Filter and Sort Toolbar */}
        <section className="mb-6">
          <FilterBar totalCount={totalMatching} />
        </section>

        {/* Gallery Grid */}
        <section>
          <Gallery
            batchId={batchId}
            onTotalLoaded={setTotalMatching}
            onStatusChange={refetchSummary}
          />
        </section>
      </div>
    </main>
  );
}
