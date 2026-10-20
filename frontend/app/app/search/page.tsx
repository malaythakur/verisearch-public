"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ApiError, search } from "@/lib/api";
import type { SearchMode, SearchResult } from "@/lib/types";
import { Gate } from "@/components/AppShell";
import {
  CredibilityBadge,
  ErrorBanner,
  ScoreBar,
} from "@/components/ui";
import { EmptyCorpusNotice, PageHint } from "@/components/Guidance";
import { useCorpus } from "@/lib/useCorpus";

const modes: SearchMode[] = ["hybrid", "neural", "keyword"];

export default function AppSearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { isEmpty } = useCorpus();

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await search({ query, mode, num_results: 10 });
      setResults(res.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Gate permission="search">
      <h1 className="text-2xl font-bold">Search</h1>
      <PageHint>
        Find passages across your corpus. Hybrid blends meaning-based (neural)
        and keyword matching; switch modes below to compare.
      </PageHint>

      {isEmpty && (
        <div className="mt-5">
          <EmptyCorpusNotice action="search" />
        </div>
      )}

      <form onSubmit={run} className="mt-4 space-y-3">
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search the corpus…"
            className="flex-1 rounded-lg border border-white/10 bg-surface px-4 py-3 outline-none ring-accent/40 focus:ring-2"
          />
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="rounded-lg bg-accent px-6 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
          >
            {loading ? "…" : "Search"}
          </button>
        </div>
        <div className="flex gap-2">
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded-full border px-3 py-1 text-xs capitalize transition ${
                mode === m
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-white/10 text-muted hover:text-white"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </form>

      <div className="mt-6 space-y-3">
        {error && <ErrorBanner message={error} />}
        {loading &&
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 skeleton rounded-xl" />
          ))}
        {!loading && results?.length === 0 && (
          <div className="rounded-xl border border-white/10 bg-surface/40 p-8 text-center text-muted">
            No matches in your corpus. Try different words, switch to{" "}
            <span className="text-accent">hybrid</span> mode, or add more
            documents.
          </div>
        )}
        <AnimatePresence>
          {!loading &&
            results?.map((r, i) => (
              <motion.article
                key={r.document_id + i}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className="rounded-xl border border-white/8 bg-surface/40 p-5"
              >
                <h3 className="truncate font-semibold">{r.title || r.url}</h3>
                <a
                  href={r.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate text-sm text-accent hover:underline"
                >
                  {r.url}
                </a>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <ScoreBar value={r.score} />
                  <CredibilityBadge
                    credibility={r.provenance.credibility_score}
                    aiLikelihood={r.provenance.ai_generated_likelihood}
                  />
                </div>
              </motion.article>
            ))}
        </AnimatePresence>
      </div>
    </Gate>
  );
}
