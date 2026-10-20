"use client";

import { motion } from "framer-motion";

export function PageHeader({
  title,
  subtitle,
}: {
  title: React.ReactNode;
  subtitle?: string;
}) {
  return (
    <div className="mb-8">
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1>
      {subtitle && <p className="mt-2 text-muted">{subtitle}</p>}
    </div>
  );
}

export function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/10">
        <motion.div
          className="h-full rounded-full bg-accent"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      <span className="tabular-nums text-xs text-muted">{value.toFixed(3)}</span>
    </div>
  );
}

export function CredibilityBadge({
  credibility,
  aiLikelihood,
}: {
  credibility: number;
  aiLikelihood: number;
}) {
  const tone =
    credibility >= 0.7
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : credibility >= 0.4
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-red-500/40 bg-red-500/10 text-red-300";
  return (
    <div className="flex flex-wrap gap-1.5 text-xs">
      <span className={`rounded-md border px-2 py-0.5 ${tone}`}>
        credibility {(credibility * 100).toFixed(0)}%
      </span>
      <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-muted">
        AI-likelihood {(aiLikelihood * 100).toFixed(0)}%
      </span>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      {label}
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      {message}
    </div>
  );
}
