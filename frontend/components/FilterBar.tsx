"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

interface FilterBarProps {
  totalCount?: number;
}

const FILTER_PRESETS = [
  { id: "all", label: "All Photos", queryVal: "" },
  { id: "best_shots", label: "★ Best Shots", queryVal: "best_shots" },
  { id: "blur", label: "Blur", queryVal: "blur" },
  { id: "duplicates", label: "Duplicates", queryVal: "duplicates" },
  { id: "closed_eyes", label: "Closed Eyes", queryVal: "closed_eyes" },
  { id: "low_score", label: "Low Score", queryVal: "low_score" },
] as const;

const CATEGORIES = [
  { id: "", label: "All Categories" },
  { id: "people", label: "People" },
  { id: "stage", label: "Stage" },
  { id: "candid", label: "Candid" },
  { id: "group", label: "Group" },
  { id: "other", label: "Other" },
] as const;

const STATUSES = [
  { id: "", label: "All Statuses" },
  { id: "keep", label: "Keep" },
  { id: "review", label: "Review" },
  { id: "reject", label: "Reject" },
] as const;

const SORT_OPTIONS = [
  { id: "score_desc", label: "Highest AI Score" },
  { id: "sharpness_desc", label: "Sharpness" },
  { id: "similarity", label: "Similarity Clusters" },
  { id: "newest", label: "Newest First" },
  { id: "oldest", label: "Oldest First" },
] as const;

export default function FilterBar({ totalCount }: FilterBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const currentFilter = searchParams.get("filter") || "";
  const currentCategory = searchParams.get("category") || "";
  const currentStatus = searchParams.get("status") || "";
  const currentSort = searchParams.get("sort") || "score_desc";

  const updateQueryParams = useCallback(
    (updates: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      // Reset pagination to page 1 whenever filters or sort change
      params.delete("page");

      for (const [key, value] of Object.entries(updates)) {
        if (!value || value === "all") {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      }

      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]/80 p-4 backdrop-blur-md">
      {/* Top row: Quick preset buttons + Sort dropdown */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Preset filter pills */}
        <div className="flex flex-wrap items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
          {FILTER_PRESETS.map((preset) => {
            const isActive =
              preset.queryVal === ""
                ? !currentFilter
                : currentFilter === preset.queryVal;

            return (
              <button
                key={preset.id}
                onClick={() => updateQueryParams({ filter: preset.queryVal })}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200 ${
                  isActive
                    ? "bg-indigo-600 text-white shadow-[0_0_12px_rgba(99,102,241,0.4)]"
                    : "bg-zinc-800/80 text-zinc-300 hover:bg-zinc-700/80 hover:text-white"
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>

        {/* Sort selector */}
        <div className="flex items-center gap-2">
          <label htmlFor="sort-select" className="text-xs font-medium text-[var(--text-muted)] whitespace-nowrap">
            Sort by:
          </label>
          <select
            id="sort-select"
            value={currentSort}
            onChange={(e) => updateQueryParams({ sort: e.target.value })}
            className="rounded-lg border border-[var(--border)] bg-zinc-900 px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-indigo-500 focus:outline-none"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bottom row: Category & Status dropdowns + Matching count */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)]/60 pt-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Category Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-[var(--text-muted)]">Category:</span>
            <select
              value={currentCategory}
              onChange={(e) => updateQueryParams({ category: e.target.value })}
              className="rounded-lg border border-[var(--border)] bg-zinc-900 px-2.5 py-1 text-xs text-[var(--text-primary)] focus:border-indigo-500 focus:outline-none"
            >
              {CATEGORIES.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>

          {/* Status Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-[var(--text-muted)]">Status:</span>
            <select
              value={currentStatus}
              onChange={(e) => updateQueryParams({ status: e.target.value })}
              className="rounded-lg border border-[var(--border)] bg-zinc-900 px-2.5 py-1 text-xs text-[var(--text-primary)] focus:border-indigo-500 focus:outline-none"
            >
              {STATUSES.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.label}
                </option>
              ))}
            </select>
          </div>

          {/* Clear Filters Button (shown if any non-default filter is set) */}
          {(currentFilter || currentCategory || currentStatus || currentSort !== "score_desc") && (
            <button
              onClick={() =>
                updateQueryParams({
                  filter: null,
                  category: null,
                  status: null,
                  sort: "score_desc",
                })
              }
              className="text-xs text-indigo-400 hover:text-indigo-300 underline underline-offset-2 ml-1"
            >
              Reset Filters
            </button>
          )}
        </div>

        {/* Counter */}
        {typeof totalCount === "number" && (
          <div className="text-xs text-[var(--text-muted)]">
            Showing <span className="font-semibold text-[var(--text-primary)]">{totalCount}</span> photos
          </div>
        )}
      </div>
    </div>
  );
}
