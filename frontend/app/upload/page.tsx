"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { uploadBatch, type RejectedFile, type UploadResponse } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "done"; result: UploadResponse }
  | { phase: "error"; message: string };

// ── Constants ─────────────────────────────────────────────────────────────────

const ACCEPTED_MIME = ["image/jpeg", "image/png", "image/webp"];
const ACCEPTED_EXT  = [".jpg", ".jpeg", ".png", ".webp"];

function isAccepted(file: File): boolean {
  const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
  return ACCEPTED_MIME.includes(file.type) || ACCEPTED_EXT.includes(ext);
}

/** De-duplicate by name + size so the same file can't be added twice. */
function mergeFiles(existing: File[], incoming: File[]): File[] {
  const keys = new Set(existing.map((f) => `${f.name}:${f.size}`));
  return [
    ...existing,
    ...incoming.filter((f) => isAccepted(f) && !keys.has(`${f.name}:${f.size}`)),
  ];
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ReasonBadge({ reason }: { reason: string }) {
  const labels: Record<string, string> = {
    unsupported_format: "Wrong format",
    file_too_large:     "Too large",
    corrupt_image:      "Corrupt image",
  };
  return (
    <span className="ml-2 rounded-full bg-red-900/40 px-2 py-0.5 text-[10px] font-medium text-red-300 border border-red-700/40">
      {labels[reason] ?? reason}
    </span>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="mt-4 w-full">
      <div className="flex justify-between mb-1.5 text-xs text-[var(--text-muted)]">
        <span>Uploading…</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--border)]">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function RejectedPanel({ rejected }: { rejected: RejectedFile[] }) {
  const [open, setOpen] = useState(false);
  if (rejected.length === 0) return null;
  return (
    <div className="mt-3 w-full rounded-xl border border-red-700/40 bg-red-950/30 overflow-hidden">
      <button
        id="rejected-panel-toggle"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-red-300 hover:bg-red-900/20 transition-colors"
      >
        <span>{rejected.length} file{rejected.length !== 1 ? "s" : ""} rejected</span>
        <svg
          className={`h-4 w-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <ul className="divide-y divide-red-900/30 border-t border-red-700/30">
          {rejected.map((r, i) => (
            <li key={i} className="flex items-center px-4 py-2.5 text-xs">
              <span className="flex-1 truncate text-[var(--text-muted)]">{r.filename}</span>
              <ReasonBadge reason={r.reason} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Drop Zone ─────────────────────────────────────────────────────────────────

interface DropZoneProps {
  onFiles: (files: File[]) => void;
  disabled: boolean;
}

function DropZone({ onFiles, disabled }: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files);
      onFiles(files);
    },
    [disabled, onFiles]
  );

  return (
    <div
      id="drop-zone"
      role="button"
      tabIndex={0}
      aria-label="Drag and drop image files here, or click to browse"
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !disabled && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={[
        "relative flex flex-col items-center justify-center gap-4",
        "w-full rounded-2xl border-2 border-dashed p-12 text-center",
        "transition-all duration-200 cursor-pointer select-none",
        disabled
          ? "border-[var(--border)] opacity-40 cursor-not-allowed"
          : dragging
          ? "border-indigo-400 bg-indigo-950/40 scale-[1.01]"
          : "border-[var(--border)] hover:border-indigo-500/60 hover:bg-indigo-950/20",
      ].join(" ")}
    >
      {/* Icon */}
      <div className={`flex h-14 w-14 items-center justify-center rounded-2xl transition-colors duration-200 ${
        dragging ? "bg-indigo-500/30" : "bg-[var(--bg-card)]"
      }`}>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round"
          className={`h-7 w-7 ${dragging ? "text-indigo-300" : "text-[var(--text-muted)]"}`}
        >
          <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>
      </div>

      <div>
        <p className="text-sm font-medium text-[var(--text-primary)]">
          {dragging ? "Drop your photos here" : "Drag & drop photos here"}
        </p>
        <p className="mt-1 text-xs text-[var(--text-muted)]">
          or <span className="text-indigo-400 underline underline-offset-2">click to browse</span>
          &nbsp;— JPG, PNG, WebP up to 25 MB each
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        id="file-input"
        multiple
        accept={ACCEPTED_EXT.join(",")}
        className="sr-only"
        onChange={(e) => {
          if (e.target.files) onFiles(Array.from(e.target.files));
          e.target.value = "";           // allow re-selecting same files
        }}
      />
    </div>
  );
}

// ── File Queue ────────────────────────────────────────────────────────────────

interface FileQueueProps {
  files: File[];
  onRemove: (index: number) => void;
  disabled: boolean;
}

function FileQueue({ files, onRemove, disabled }: FileQueueProps) {
  if (files.length === 0) return null;

  const totalBytes = files.reduce((s, f) => s + f.size, 0);

  return (
    <div className="mt-4 glass-card overflow-hidden">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-widest text-[var(--text-muted)]">
          Selected
        </span>
        <span id="file-counter" className="text-xs font-medium text-indigo-300">
          {files.length} photo{files.length !== 1 ? "s" : ""} · {formatBytes(totalBytes)}
        </span>
      </div>
      <ul className="max-h-52 divide-y divide-[var(--border)] overflow-y-auto">
        {files.map((file, i) => (
          <li key={`${file.name}:${file.size}`}
            className="flex items-center gap-3 px-4 py-2.5 text-xs"
          >
            <span className="flex-1 truncate text-[var(--text-muted)]">{file.name}</span>
            <span className="shrink-0 text-[var(--text-muted)]">{formatBytes(file.size)}</span>
            {!disabled && (
              <button
                aria-label={`Remove ${file.name}`}
                onClick={() => onRemove(i)}
                className="shrink-0 rounded p-0.5 text-[var(--text-muted)] hover:text-red-400 transition-colors"
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UploadPage() {
  const router = useRouter();
  const [files, setFiles]           = useState<File[]>([]);
  const [uploadState, setUploadState] = useState<UploadState>({ phase: "idle" });

  const isUploading = uploadState.phase === "uploading";

  const addFiles = useCallback((incoming: File[]) => {
    setFiles((prev) => mergeFiles(prev, incoming));
  }, []);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleUpload = async () => {
    if (files.length === 0 || isUploading) return;
    setUploadState({ phase: "uploading", progress: 0 });

    try {
      const result = await uploadBatch(files, (pct) => {
        setUploadState({ phase: "uploading", progress: pct });
      });
      setUploadState({ phase: "done", result });
      setFiles([]);
      // Navigate to the analyzing screen
      if (result.accepted_count > 0) {
        router.push(`/analyzing/${result.batch_id}`);
      }
    } catch (err: unknown) {
      setUploadState({
        phase: "error",
        message: err instanceof Error ? err.message : "Unknown error",
      });
    }
  };

  const reset = () => {
    setFiles([]);
    setUploadState({ phase: "idle" });
  };

  return (
    <main className="relative min-h-dvh overflow-hidden px-4 py-16">
      {/* Ambient blobs */}
      <div aria-hidden className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[500px] -translate-x-1/2 rounded-full bg-indigo-600/15 blur-[120px]" />
      <div aria-hidden className="pointer-events-none absolute bottom-0 right-0 h-[340px] w-[340px] rounded-full bg-purple-700/10 blur-[100px]" />

      <div className="relative z-10 mx-auto max-w-2xl">

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
            Phase 2 · Upload
          </span>
        </div>

        {/* Title */}
        <h1 className="mb-1 text-3xl font-extrabold tracking-tight text-[var(--text-primary)] sm:text-4xl">
          Upload Your Photos
        </h1>
        <p className="mb-8 text-sm text-[var(--text-muted)]">
          Drop your event photos below. We&apos;ll validate, store, and thumbnail
          them — AI analysis starts in the next phase.
        </p>

        {/* ── Result panel (done state) ─────────────────────────────────── */}
        {uploadState.phase === "done" && (
          <div id="result-panel" className="mb-6 glass-card overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-green-500/20">
                  <svg className="h-4 w-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <span className="text-sm font-semibold text-[var(--text-primary)]">Upload complete</span>
              </div>
              <button
                id="upload-again-btn"
                onClick={reset}
                className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                Upload another batch
              </button>
            </div>

            <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
              <div className="px-5 py-4 text-center">
                <p className="text-2xl font-bold text-green-400">{uploadState.result.accepted_count}</p>
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">accepted</p>
              </div>
              <div className="px-5 py-4 text-center">
                <p className="text-2xl font-bold text-red-400">{uploadState.result.rejected_count}</p>
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">rejected</p>
              </div>
            </div>

            <div className="border-t border-[var(--border)] px-5 py-3">
              <p className="text-xs text-[var(--text-muted)]">
                Batch ID:{" "}
                <code id="batch-id" className="font-mono text-indigo-400">
                  {uploadState.result.batch_id}
                </code>
              </p>
            </div>

            <RejectedPanel rejected={uploadState.result.rejected} />
          </div>
        )}

        {/* ── Error panel ───────────────────────────────────────────────── */}
        {uploadState.phase === "error" && (
          <div id="error-panel" className="mb-6 flex items-start gap-3 rounded-xl border border-red-700/50 bg-red-950/30 px-4 py-4">
            <svg className="mt-0.5 h-4 w-4 shrink-0 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-red-300">Upload failed</p>
              <p className="mt-0.5 text-xs text-red-400/80">{uploadState.message}</p>
            </div>
            <button
              id="retry-btn"
              onClick={() => setUploadState({ phase: "idle" })}
              className="shrink-0 rounded-lg border border-red-700/50 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-900/30 transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {/* ── Drop zone (idle / error) ──────────────────────────────────── */}
        {uploadState.phase !== "done" && (
          <>
            <DropZone onFiles={addFiles} disabled={isUploading} />
            <FileQueue files={files} onRemove={removeFile} disabled={isUploading} />

            {/* Progress bar */}
            {uploadState.phase === "uploading" && (
              <ProgressBar pct={uploadState.progress} />
            )}

            {/* Action button */}
            <button
              id="start-upload-btn"
              onClick={handleUpload}
              disabled={files.length === 0 || isUploading}
              className={[
                "mt-5 w-full rounded-xl py-3.5 text-sm font-semibold",
                "transition-all duration-200",
                files.length > 0 && !isUploading
                  ? "bg-gradient-to-r from-indigo-600 to-purple-600 text-white hover:from-indigo-500 hover:to-purple-500 shadow-[0_0_24px_var(--accent-glow)]"
                  : "bg-[var(--bg-card)] text-[var(--text-muted)] cursor-not-allowed border border-[var(--border)]",
              ].join(" ")}
            >
              {isUploading
                ? `Uploading… ${uploadState.progress}%`
                : files.length > 0
                ? `Start AI Analysis — ${files.length} photo${files.length !== 1 ? "s" : ""}`
                : "Select photos to continue"}
            </button>
          </>
        )}
      </div>
    </main>
  );
}
