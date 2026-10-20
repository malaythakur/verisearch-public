"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ApiError } from "@/lib/api";
import { streamAnswer } from "@/lib/stream";
import type { Citation } from "@/lib/types";
import { Gate } from "@/components/AppShell";
import { ErrorBanner } from "@/components/ui";
import { EmptyCorpusNotice, PageHint, ExampleChips } from "@/components/Guidance";
import { useCorpus } from "@/lib/useCorpus";

export default function AppAnswerPage() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const { isEmpty } = useCorpus();

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim() || streaming) return;
    setAnswer("");
    setCitations([]);
    setError(null);
    setStreaming(true);
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      for await (const ev of streamAnswer(query, undefined, ac.signal)) {
        if (ev.type === "token") setAnswer((a) => a + ev.text);
        else if (ev.type === "citation") setCitations((c) => [...c, ev.citation]);
        else if (ev.type === "done") {
          if (ev.answer) setAnswer(ev.answer);
          if (ev.citations?.length) setCitations(ev.citations);
        } else if (ev.type === "error") setError(ev.message);
      }
    } catch (err) {
      if (!ac.signal.aborted)
        setError(err instanceof ApiError ? err.message : "Stream failed");
    } finally {
      setStreaming(false);
    }
  }

  return (
    <Gate permission="answer">
      <h1 className="text-2xl font-bold">Cited Answers</h1>
      <PageHint>
        Ask a question in plain language. The answer is generated only from
        documents in your corpus, and every claim links back to its source.
      </PageHint>

      {isEmpty && (
        <div className="mt-5">
          <EmptyCorpusNotice action="answer" />
        </div>
      )}

      <form onSubmit={ask} className="mt-4 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. What were the key findings? Summarize the main risks."
          className="flex-1 rounded-lg border border-white/10 bg-surface px-4 py-3 outline-none ring-accent/40 focus:ring-2"
        />
        <button
          type="submit"
          disabled={streaming || !query.trim()}
          className="rounded-lg bg-accent px-6 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
        >
          {streaming ? "Streaming…" : "Ask"}
        </button>
      </form>

      {!isEmpty && !answer && !streaming && (
        <div className="mt-3">
          <ExampleChips
            examples={[
              "Summarize the main points",
              "What are the key risks?",
              "What does it say about pricing?",
            ]}
            onPick={setQuery}
          />
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {(answer || streaming) && (
        <div className="mt-6 grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          <article className="rounded-2xl border border-white/8 bg-surface/40 p-6">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">
              Answer
            </h2>
            <p className="whitespace-pre-wrap leading-relaxed">
              {answer}
              {streaming && (
                <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-accent align-middle" />
              )}
            </p>
          </article>
          <aside className="rounded-2xl border border-white/8 bg-surface/40 p-6">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">
              Citations ({citations.length})
            </h2>
            <div className="space-y-2">
              <AnimatePresence>
                {citations.map((c, i) => (
                  <motion.div
                    key={`${c.document_id}-${i}`}
                    initial={{ opacity: 0, x: 12 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="rounded-lg border border-white/10 bg-white/5 p-3 text-sm"
                  >
                    <span className="font-mono text-xs text-accent">[{i + 1}]</span>
                    <p className="mt-1 truncate font-mono text-xs text-muted">
                      {c.document_id}
                    </p>
                    <p className="mt-1 text-xs text-muted">
                      span {c.answer_start}–{c.answer_end}
                    </p>
                  </motion.div>
                ))}
              </AnimatePresence>
              {citations.length === 0 && (
                <p className="text-sm text-muted">Citations stream in here.</p>
              )}
            </div>
          </aside>
        </div>
      )}
    </Gate>
  );
}
