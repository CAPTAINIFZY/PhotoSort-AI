"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/* ------------------------------------------------------------------ */
/* Types                                                                */
/* ------------------------------------------------------------------ */
type ConnectionState = "checking" | "connected" | "disconnected";

interface HealthPayload {
  status: string;
  db: boolean;
  storage: boolean;
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                       */
/* ------------------------------------------------------------------ */

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${
        ok ? "bg-green-500 shadow-[0_0_6px_#22c55e]" : "bg-red-500 shadow-[0_0_6px_#ef4444]"
      }`}
      aria-hidden="true"
    />
  );
}

function PulsingRing() {
  return (
    <span className="relative flex h-3 w-3">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
      <span className="relative inline-flex h-3 w-3 rounded-full bg-indigo-500" />
    </span>
  );
}

function ConnectionBadge({ state }: { state: ConnectionState }) {
  if (state === "checking") {
    return (
      <div
        id="connection-badge-checking"
        className="flex items-center gap-2.5 rounded-full border border-indigo-700/60 bg-indigo-950/50 px-4 py-2 text-sm font-medium text-indigo-300"
      >
        <PulsingRing />
        Connecting to backend…
      </div>
    );
  }

  const connected = state === "connected";
  return (
    <div
      id={`connection-badge-${state}`}
      className={`flex items-center gap-2.5 rounded-full border px-4 py-2 text-sm font-medium transition-all duration-500 ${
        connected
          ? "border-green-700/60 bg-green-950/50 text-green-300"
          : "border-red-700/60  bg-red-950/50  text-red-300"
      }`}
    >
      <StatusDot ok={connected} />
      Backend: {connected ? "connected" : "disconnected"}
    </div>
  );
}

function HealthCard({ health }: { health: HealthPayload | null }) {
  if (!health) return null;

  const rows = [
    { label: "API status", value: health.status === "ok" ? "OK" : health.status, ok: health.status === "ok" },
    { label: "Database",   value: health.db      ? "reachable" : "unreachable", ok: health.db },
    { label: "Storage",    value: health.storage  ? "ready"     : "missing",    ok: health.storage },
  ];

  return (
    <div
      id="health-card"
      className="glass-card mt-8 w-full max-w-sm overflow-hidden"
    >
      <div className="border-b border-[var(--border)] px-5 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-[var(--text-muted)]">
          Health report
        </p>
      </div>
      <ul className="divide-y divide-[var(--border)]">
        {rows.map(({ label, value, ok }) => (
          <li
            key={label}
            className="flex items-center justify-between px-5 py-3 text-sm"
          >
            <span className="text-[var(--text-muted)]">{label}</span>
            <span className="flex items-center gap-2 font-medium">
              <StatusDot ok={ok} />
              {value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                 */
/* ------------------------------------------------------------------ */
export default function HomePage() {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>("checking");
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const backendUrl =
    process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

  const checkHealth = async () => {
    setConnectionState("checking");
    setErrorMsg(null);
    try {
      const res = await fetch(`${backendUrl}/health`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: HealthPayload = await res.json();
      setHealth(data);
      setConnectionState("connected");
    } catch (err: unknown) {
      setHealth(null);
      setConnectionState("disconnected");
      setErrorMsg(err instanceof Error ? err.message : "Unknown error");
    }
  };

  useEffect(() => {
    checkHealth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-16">
      {/* Ambient background blobs */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-32 left-1/2 h-[480px] w-[480px] -translate-x-1/2 rounded-full bg-indigo-600/20 blur-[120px]"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute bottom-0 right-0 h-[320px] w-[320px] rounded-full bg-purple-700/15 blur-[100px]"
      />

      {/* Hero content */}
      <div className="relative z-10 flex flex-col items-center text-center">
        {/* Logo mark */}
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 shadow-[0_0_40px_var(--accent-glow)]">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="white"
            className="h-8 w-8"
            aria-hidden="true"
          >
            <path d="M12 9a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 9Z" />
            <path
              fillRule="evenodd"
              d="M9.344 3.071a49.52 49.52 0 0 1 5.312 0c.967.052 1.83.585 2.332 1.39l.821 1.317c.24.383.645.643 1.11.71.386.054.77.113 1.152.177 1.432.239 2.429 1.493 2.429 2.909V18a3 3 0 0 1-3 3h-15a3 3 0 0 1-3-3V9.574c0-1.416.997-2.67 2.429-2.909.382-.064.766-.123 1.151-.178a1.56 1.56 0 0 0 1.11-.71l.822-1.315a2.942 2.942 0 0 1 2.332-1.39ZM6.75 12.75a5.25 5.25 0 1 1 10.5 0 5.25 5.25 0 0 1-10.5 0Zm12-1.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z"
              clipRule="evenodd"
            />
          </svg>
        </div>

        {/* Heading */}
        <h1 className="bg-gradient-to-b from-white to-indigo-200 bg-clip-text text-5xl font-extrabold tracking-tight text-transparent sm:text-6xl">
          PhotoSort&nbsp;AI
        </h1>
        <p className="mt-3 max-w-md text-base text-[var(--text-muted)]">
          AI-powered event photo culling — automatically score, rank, and
          select your best shots.
        </p>

        {/* Phase badge */}
        <span className="mt-5 inline-block rounded-full border border-indigo-600/40 bg-indigo-950/60 px-3 py-0.5 text-xs font-medium text-indigo-400">
          Phase 2 · Upload System
        </span>

        {/* Connection badge */}
        <div className="mt-8">
          <ConnectionBadge state={connectionState} />
        </div>

        {/* Error detail */}
        {errorMsg && (
          <p
            id="error-message"
            className="mt-3 text-xs text-red-400"
            role="alert"
          >
            {errorMsg}
          </p>
        )}

        {/* Health details card */}
        <HealthCard health={health} />

        {/* Actions */}
        <div className="mt-6 flex flex-col items-center gap-3 sm:flex-row">
          <Link
            id="upload-cta"
            href="/upload"
            className="w-full sm:w-auto rounded-full bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-2.5 text-center text-sm font-semibold text-white shadow-[0_0_20px_var(--accent-glow)] transition-all duration-200 hover:from-indigo-500 hover:to-purple-500"
          >
            Upload Photos →
          </Link>
          <button
            id="retry-button"
            onClick={checkHealth}
            disabled={connectionState === "checking"}
            className="w-full sm:w-auto rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-5 py-2.5 text-sm font-medium text-[var(--text-muted)] transition-all duration-200 hover:border-indigo-500/60 hover:text-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {connectionState === "checking" ? "Checking…" : "Retry"}
          </button>
        </div>
      </div>
    </main>
  );
}
