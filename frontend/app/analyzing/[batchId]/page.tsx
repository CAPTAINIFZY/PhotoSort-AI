"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  BACKEND_URL,
  startAnalysis,
  getBatchStatus,
  getBatchErrors,
  getBatchPhotos,
  type BatchStatus,
  type BatchErrorItem,
  type BatchPhotoItem,
} from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type PageState =
  | { phase: "starting" }
  | { phase: "analyzing"; status: BatchStatus }
  | { phase: "done";      status: BatchStatus }
  | { phase: "error";     message: string };

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtEta(elapsedMs: number, processed: number, total: number): string {
  if (processed === 0 || total === 0) return "—";
  const ratePerMs = processed / elapsedMs;
  const remaining = total - processed;
  const etaMs = remaining / ratePerMs;
  const s = Math.round(etaMs / 1000);
  if (s < 60) return `~${s}s`;
  const m = Math.floor(s / 60);
  return `~${m}m ${s % 60}s`;
}

function pct(processed: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((processed / total) * 100));
}

// ── Signal checklist (visual — backend runs them all together per image) ──────

const SIGNALS = [
  { id: "blur",        label: "Detecting blur",             icon: "◎" },
  { id: "exposure",    label: "Analysing exposure",          icon: "☀" },
  { id: "faces",       label: "Checking faces",              icon: "◉" },
  { id: "eyes",        label: "Detecting closed eyes",       icon: "◑" },
  { id: "similarity",  label: "Comparing similar frames",    icon: "⊕" },
  { id: "classify",    label: "Classifying photo types",     icon: "◈" },
  { id: "composition", label: "Evaluating composition",      icon: "◫" },
  { id: "ranking",     label: "Ranking best shots",          icon: "★" },
] as const;

function SignalRow({
  label,
  icon,
  progress,
}: {
  label: string;
  icon: string;
  progress: number;   // 0–100
}) {
  const done   = progress >= 100;
  const active = progress > 0 && !done;
  return (
    <div className="flex items-center gap-3 py-2">
      <span
        className={[
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold transition-colors duration-500",
          done
            ? "bg-green-500/20 text-green-400"
            : active
            ? "bg-indigo-500/20 text-indigo-400 animate-pulse"
            : "bg-[var(--bg-card)] text-[var(--text-muted)]",
        ].join(" ")}
      >
        {done ? "✓" : icon}
      </span>
      <span
        className={[
          "text-sm transition-colors duration-300",
          done
            ? "text-green-300"
            : active
            ? "text-[var(--text-primary)]"
            : "text-[var(--text-muted)]",
        ].join(" ")}
      >
        {label}
      </span>
      {active && (
        <span className="ml-auto text-xs text-indigo-400 animate-pulse">
          Running…
        </span>
      )}
      {done && (
        <span className="ml-auto text-xs text-green-400">Done</span>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AnalyzingPage({
  params,
}: {
  params: { batchId: string };
}) {
  const { batchId } = params;
  const router  = useRouter();
  const [state, setState] = useState<PageState>({ phase: "starting" });
  const [errors, setErrors] = useState<BatchErrorItem[]>([]);
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [recentThumbnails, setRecentThumbnails] = useState<BatchPhotoItem[]>([]);

  const startTimeRef = useRef<number>(0);
  const pollRef      = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    try {
      const status = await getBatchStatus(batchId);
      setState({ phase: status.status === "completed" || status.status === "failed" ? "done" : "analyzing", status });

      if (status.processed > 0) {
        getBatchPhotos({ batchId, page: 1, pageSize: 8 })
          .then((res) => {
            if (res && res.photos) setRecentThumbnails(res.photos);
          })
          .catch(() => {});
      }

      if (status.status === "completed" || status.status === "failed") {
        stopPolling();
        if (status.failed > 0) {
          getBatchErrors(batchId).then(setErrors).catch(() => {});
        }
        if (status.status === "completed" && status.failed === 0) {
          setTimeout(() => {
            router.push(`/dashboard/${batchId}`);
          }, 2000);
        }
      }
    } catch (err: unknown) {
      // Don't stop polling on transient network errors — just skip this tick
      console.warn("Status poll failed:", err);
    }
  }, [batchId, stopPolling, router]);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        await startAnalysis(batchId);
        if (cancelled) return;

        startTimeRef.current = Date.now();
        setState({ phase: "starting" });

        // First poll immediately, then every second
        await poll();
        if (!cancelled) {
          pollRef.current = setInterval(poll, 1000);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setState({
            phase:   "error",
            message: err instanceof Error ? err.message : "Unknown error",
          });
        }
      }
    }

    init();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [batchId, poll, stopPolling]);

  // ── Derived display values ───────────────────────────────────────────────

  const status     = state.phase === "analyzing" || state.phase === "done" ? state.status : null;
  const total      = status?.total      ?? 0;
  const processed  = status?.processed  ?? 0;
  const failed     = status?.failed     ?? 0;
  // A failed image is finished too.  Include it in visual progress and ETA so
  // a batch with a corrupt image does not appear stuck below 100%.
  const completed  = processed + failed;
  const progress   = pct(completed, total);
  const elapsedMs  = startTimeRef.current ? Date.now() - startTimeRef.current : 0;
  const eta        = fmtEta(elapsedMs, completed, total);
  const isDone     = state.phase === "done";
  const isError    = state.phase === "error";

  // Signal checklist progress: since all signals run together per image,
  // we approximate each signal's completion from overall processed count.
  // The 4 signals animate in overlapping waves for visual interest.
  const signalProgress = (offset: number) =>
    Math.min(100, Math.max(0, pct(completed + offset, total)));

  return (
    <main className="relative min-h-dvh overflow-hidden px-4 py-16">
      {/* Ambient blobs */}
      <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[500px] -translate-x-1/2 rounded-full bg-indigo-600/15 blur-[120px]" />
      <div aria-hidden className="pointer-events-none absolute bottom-0 right-0 h-[340px] w-[340px] rounded-full bg-purple-700/10 blur-[100px]" />

      <div className="relative z-10 mx-auto max-w-xl">

        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" className="h-5 w-5">
                <path d="M12 9a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 9Z" />
                <path fillRule="evenodd" d="M9.344 3.071a49.52 49.52 0 0 1 5.312 0c.967.052 1.83.585 2.332 1.39l.821 1.317c.24.383.645.643 1.11.71.386.054.77.113 1.152.177 1.432.239 2.429 1.493 2.429 2.909V18a3 3 0 0 1-3 3h-15a3 3 0 0 1-3-3V9.574c0-1.416.997-2.67 2.429-2.909.382-.064.766-.123 1.151-.178a1.56 1.56 0 0 0 1.11-.71l.822-1.315a2.942 2.942 0 0 1 2.332-1.39ZM6.75 12.75a5.25 5.25 0 1 1 10.5 0 5.25 5.25 0 0 1-10.5 0Zm12-1.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z" clipRule="evenodd" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-indigo-300 transition-colors">
              PhotoSort AI
            </span>
          </Link>
          <span className="rounded-full border border-indigo-600/40 bg-indigo-950/60 px-3 py-0.5 text-xs font-medium text-indigo-400">
            Pipeline Analysis
          </span>
        </div>

        {/* ── Error ─────────────────────────────────────────────────────── */}
        {isError && (
          <div id="analysis-error" className="glass-card p-6 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/20">
              <svg className="h-7 w-7 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">Analysis failed to start</h1>
            <p className="mt-2 text-sm text-[var(--text-muted)]">
              {(state as { phase: "error"; message: string }).message}
            </p>
            <Link
              href="/upload"
              className="mt-5 inline-block rounded-full border border-[var(--border)] px-5 py-2 text-sm text-[var(--text-muted)] hover:border-indigo-500/60 hover:text-indigo-300 transition-colors"
            >
              ← Back to Upload
            </Link>
          </div>
        )}

        {/* ── Analysing / Done ───────────────────────────────────────────── */}
        {!isError && (
          <>
            {/* Title */}
            <h1 className="mb-1 text-3xl font-extrabold tracking-tight text-[var(--text-primary)]">
              {isDone ? "Analysis complete" : "Analysing your photos…"}
            </h1>
            <p className="mb-8 text-sm text-[var(--text-muted)]">
              {isDone
                ? `${processed} of ${total} photos processed${failed > 0 ? `, ${failed} could not be processed` : ""}.`
                : `Running sharpness, exposure, face, and eye-state detection on ${total} photos.`}
            </p>

            {/* Main progress card */}
            <div id="progress-card" className="glass-card overflow-hidden">
              {/* Counter header */}
              <div className="flex items-baseline justify-between border-b border-[var(--border)] px-5 py-4">
                <div className="flex items-center gap-2.5">
                  <span id="progress-counter" className="text-2xl font-bold text-[var(--text-primary)]">
                    {completed}
                    <span className="ml-1 text-base font-normal text-[var(--text-muted)]">
                      / {total} photos
                    </span>
                  </span>
                  {failed > 0 && (
                    <span className="rounded-full border border-amber-500/40 bg-amber-950/60 px-2 py-0.5 text-xs text-amber-300 font-medium">
                      {failed} failed
                    </span>
                  )}
                </div>
                {!isDone && (
                  <span id="eta-display" className="text-xs text-[var(--text-muted)]">
                    ETA {eta}
                  </span>
                )}
                {isDone && failed === 0 && (
                  <span className="text-xs font-medium text-green-400">✓ All done</span>
                )}
                {isDone && failed > 0 && (
                  <button
                    onClick={() => setShowErrorDetails(!showErrorDetails)}
                    className="text-xs font-medium text-amber-400 hover:text-amber-300 underline cursor-pointer"
                  >
                    {showErrorDetails ? "Hide failed details" : "View failed details"}
                  </button>
                )}
              </div>

              {/* Progress bar */}
              <div className="px-5 pt-4 pb-2">
                <div className="h-2.5 w-full overflow-hidden rounded-full bg-[var(--border)]">
                  <div
                    id="analysis-progress-bar"
                    className={[
                      "h-full rounded-full transition-all duration-700",
                      isDone
                        ? "bg-gradient-to-r from-green-500 to-emerald-400"
                        : "bg-gradient-to-r from-indigo-500 to-purple-500",
                    ].join(" ")}
                    style={{ width: `${isDone ? 100 : progress}%` }}
                  />
                </div>
                <p className="mt-1.5 text-right text-xs text-[var(--text-muted)]">
                  {isDone ? 100 : progress}%
                </p>
              </div>

              {/* Signal checklist */}
              <div className="divide-y divide-[var(--border)] border-t border-[var(--border)] px-5">
                {SIGNALS.map((sig, idx) => (
                  <SignalRow
                    key={sig.id}
                    label={sig.label}
                    icon={sig.icon}
                    progress={isDone ? 100 : signalProgress(SIGNALS.length - idx)}
                  />
                ))}
              </div>

              {/* Live thumbnail preview strip */}
              {recentThumbnails.length > 0 && (
                <div className="border-t border-[var(--border)] px-5 py-3.5 bg-black/10">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-[var(--text-muted)] flex items-center gap-1.5">
                      <span className="flex h-2 w-2 relative">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                      </span>
                      Live Preview ({recentThumbnails.length} frames)
                    </span>
                    <span className="text-[10px] text-zinc-500 font-mono">Real-time thumbnails</span>
                  </div>
                  <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
                    {recentThumbnails.map((photo) => (
                      <div
                        key={photo.id}
                        className="group relative h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-[var(--border)] bg-zinc-900/60 shadow-sm transition-transform hover:scale-105"
                      >
                        <img
                          src={`${BACKEND_URL}${photo.thumbnail_url}`}
                          alt={photo.filename}
                          className="h-full w-full object-cover"
                          onError={(e) => {
                            (e.target as HTMLImageElement).style.opacity = "0.3";
                          }}
                        />
                        {photo.score != null && (
                          <div className="absolute bottom-0 inset-x-0 bg-black/70 backdrop-blur-xs py-0.5 text-center text-[9px] font-bold text-white">
                            {Math.round(photo.score)}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error details panel */}
              {showErrorDetails && errors.length > 0 && (
                <div className="border-t border-amber-500/20 bg-amber-950/20 px-5 py-3 text-xs">
                  <p className="font-semibold text-amber-300 mb-2">Failed Files ({errors.length}):</p>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto">
                    {errors.map((err, i) => (
                      <div key={i} className="flex justify-between items-center text-amber-400/90 font-mono text-[11px] gap-2">
                        <span className="truncate max-w-[240px] font-semibold">{err.filename}</span>
                        <span className="text-[10px] text-zinc-400 truncate">[{err.stage}] {err.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Footer: batch ID */}
              <div className="border-t border-[var(--border)] px-5 py-3">
                <p className="text-xs text-[var(--text-muted)]">
                  Batch ID:{" "}
                  <code className="font-mono text-indigo-400">{batchId}</code>
                </p>
              </div>
            </div>

            {/* Done actions */}
            {isDone && (
              <div id="done-actions" className="mt-6 flex flex-col gap-3 sm:flex-row">
                <button
                  id="view-results-btn"
                  onClick={() => {
                    router.push(`/dashboard/${batchId}`);
                  }}
                  className="w-full sm:w-auto rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-3 text-center text-sm font-semibold text-white shadow-[0_0_20px_var(--accent-glow)] transition-all hover:from-indigo-500 hover:to-purple-500"
                >
                  View Dashboard &amp; Gallery →
                </button>
                <Link
                  href="/upload"
                  className="w-full sm:w-auto rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-6 py-3 text-center text-sm font-medium text-[var(--text-muted)] hover:border-indigo-500/60 hover:text-indigo-300 transition-colors"
                >
                  Upload another batch
                </Link>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}
