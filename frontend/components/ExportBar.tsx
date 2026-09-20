"use client";

import { useState } from "react";
import { exportSelectedZip, downloadExportReport } from "@/lib/api";

interface ExportBarProps {
  batchId: string;
  selectedCount: number;
  totalCount: number;
}

export default function ExportBar({
  batchId,
  selectedCount,
  totalCount,
}: ExportBarProps) {
  const [isExportingZip, setIsExportingZip] = useState(false);
  const [isExportingCsv, setIsExportingCsv] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleExportZip = async () => {
    if (selectedCount === 0) return;
    try {
      setIsExportingZip(true);
      setErrorMessage(null);
      await exportSelectedZip(batchId);
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to generate ZIP export"
      );
    } finally {
      setIsExportingZip(false);
    }
  };

  const handleDownloadCsv = async () => {
    try {
      setIsExportingCsv(true);
      setErrorMessage(null);
      await downloadExportReport(batchId);
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to download CSV report"
      );
    } finally {
      setIsExportingCsv(false);
    }
  };

  const hasSelection = selectedCount > 0;

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]/90 p-4 shadow-xl backdrop-blur-md">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Selection Count Pill */}
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500/20 text-emerald-400 font-bold text-sm shadow-inner">
            ✓
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                Selected for Export:
              </span>
              <span className="font-mono text-sm font-bold text-emerald-300">
                {selectedCount}
              </span>
              <span className="text-xs text-[var(--text-muted)]">
                / {totalCount} photos (Status: Keep)
              </span>
            </div>
            {!hasSelection && (
              <p className="text-[11px] text-amber-400/90 mt-0.5">
                Mark photos as Keep to include them in the export package.
              </p>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Download Report (CSV) */}
          <button
            onClick={handleDownloadCsv}
            disabled={isExportingCsv}
            title="Download full culling summary and per-photo audit CSV report"
            className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-zinc-900 px-3.5 py-2 text-xs font-semibold text-[var(--text-primary)] hover:border-zinc-500 disabled:opacity-50 transition-colors"
          >
            {isExportingCsv ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-zinc-400 border-t-transparent" />
                <span>Exporting CSV...</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>Download Report (CSV)</span>
              </>
            )}
          </button>

          {/* Download Selected (ZIP) */}
          <button
            onClick={handleExportZip}
            disabled={!hasSelection || isExportingZip}
            title={hasSelection ? "Download all Keep photos in full resolution ZIP" : "No photos marked as Keep"}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 px-4 py-2 text-xs font-semibold text-white shadow-lg shadow-emerald-600/20 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {isExportingZip ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                <span>Building ZIP...</span>
              </>
            ) : (
              <>
                <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                <span>Download Selected (ZIP)</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Error alert */}
      {errorMessage && (
        <div className="mt-1 rounded-lg border border-red-500/30 bg-red-950/40 p-2 text-xs text-red-300">
          {errorMessage}
        </div>
      )}
    </div>
  );
}
