"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ApiError, fetchWeb, type WebFetchResult } from "@/lib/api";
import { Gate } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ErrorBanner, Spinner } from "@/components/ui";

export default function AppWebPage() {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [indexAfter, setIndexAfter] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<WebFetchResult | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const target = url.trim();
    if (!target) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetchWeb(target, { index: indexAfter, include_text: true });
      setResult(res);
      toast(
        res.indexed ? "Fetched and indexed into corpus" : "Fetched from the web",
        "success"
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Web fetch failed";
      setError(msg);
      toast(msg, "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Gate permission="search">
      <h1 className="text-2xl font-bold">Web Fetch</h1>
      <p className="mt-1 text-muted">
        Retrieve content from the live web. Requests go through the
        compliance-checked crawler (robots.txt, per-host throttling, domain
        opt-out). Optionally index the result so Search and Answers can use it.
      </p>

      <form
        onSubmit={submit}
        className="mt-5 space-y-4 rounded-2xl border border-white/8 bg-surface/40 p-6"
      >
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/article"
          className="w-full rounded-lg border border-white/10 bg-base px-4 py-3 outline-none ring-accent/40 focus:ring-2"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={indexAfter}
              onChange={(e) => setIndexAfter(e.target.checked)}
              className="h-4 w-4 accent-[var(--accent,#22d3ee)]"
            />
            Index into corpus after fetching
          </label>
          <button
            type="submit"
            disabled={!url.trim() || loading}
            className="rounded-lg bg-accent px-6 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
          >
            {loading ? "Fetching…" : "Fetch URL"}
          </button>
        </div>
        <p className="text-xs text-muted">
          Only http(s) URLs are fetched. Pages disallowed by robots.txt or
          opted-out domains are refused.
        </p>
      </form>

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {loading && (
        <div className="mt-4">
          <Spinner label="Fetching from the web…" />
        </div>
      )}

      {result && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-6 space-y-4"
        >
          <div className="rounded-xl border border-white/8 bg-surface/40 p-5">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-emerald-300">
                HTTP {result.http_status}
              </span>
              <span className="rounded-md bg-white/5 px-2 py-0.5 text-muted">
                {result.content_type || "unknown type"}
              </span>
              <span className="rounded-md bg-white/5 px-2 py-0.5 text-muted">
                {result.characters.toLocaleString()} chars
              </span>
              {result.indexed && (
                <span className="rounded-md bg-accent/15 px-2 py-0.5 text-accent">
                  indexed · v{result.version}
                </span>
              )}
            </div>
            <a
              href={result.canonical_url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-3 block truncate font-mono text-sm text-accent hover:underline"
            >
              {result.canonical_url}
            </a>
            {result.indexed && result.document_id && (
              <p className="mt-1 truncate font-mono text-xs text-muted">
                document_id: {result.document_id}
              </p>
            )}
          </div>

          {result.text != null && (
            <div className="rounded-xl border border-white/8 bg-surface/40 p-5">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">
                Extracted text
              </h2>
              <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-white/90">
                {result.text}
              </pre>
            </div>
          )}
        </motion.div>
      )}
    </Gate>
  );
}
