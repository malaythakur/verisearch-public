"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ApiError,
  createResearch,
  getResearch,
  getResearchEvents,
} from "@/lib/api";
import type { ResearchEvent, ResearchReport } from "@/lib/types";
import { Gate } from "@/components/AppShell";
import { ErrorBanner, Spinner } from "@/components/ui";
import { EmptyCorpusNotice, PageHint } from "@/components/Guidance";
import { useCorpus } from "@/lib/useCorpus";

export default function AppResearchPage() {
  const [goal, setGoal] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [events, setEvents] = useState<ResearchEvent[]>([]);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastIdRef = useRef(0);
  const { isEmpty } = useCorpus();

  useEffect(() => () => stop(), []);
  function stop() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }

  async function launch(e: React.FormEvent) {
    e.preventDefault();
    if (!goal.trim() || running) return;
    setEvents([]);
    setReport(null);
    setError(null);
    lastIdRef.current = 0;
    setRunning(true);
    try {
      const { job_id } = await createResearch(goal.trim());
      setJobId(job_id);
      poll(job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Launch failed");
      setRunning(false);
    }
  }

  function poll(job_id: string) {
    stop();
    pollRef.current = setInterval(async () => {
      try {
        const { events: ne } = await getResearchEvents(
          job_id,
          lastIdRef.current || undefined
        );
        if (ne.length) {
          lastIdRef.current = ne[ne.length - 1].event_id;
          setEvents((p) => [...p, ...ne]);
        }
        if (ne.find((x) => ["completed", "failed", "done"].includes(x.type))) {
          stop();
          setReport(await getResearch(job_id));
          setRunning(false);
        }
      } catch (err) {
        stop();
        setError(err instanceof ApiError ? err.message : "Polling failed");
        setRunning(false);
      }
    }, 1500);
  }

  return (
    <Gate permission="research">
      <h1 className="text-2xl font-bold">Research</h1>
      <PageHint>
        Describe a goal and the agent runs multiple search-and-reason steps over
        your corpus, then returns a structured report. This can take a minute.
      </PageHint>

      {isEmpty && (
        <div className="mt-5">
          <EmptyCorpusNotice action="research" />
        </div>
      )}

      <form onSubmit={launch} className="mt-4 flex gap-2">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Compare the risks and opportunities across these documents"
          className="flex-1 rounded-lg border border-white/10 bg-surface px-4 py-3 outline-none ring-accent/40 focus:ring-2"
        />
        <button
          type="submit"
          disabled={running || !goal.trim()}
          className="rounded-lg bg-accent px-6 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
        >
          {running ? "Researching…" : "Launch"}
        </button>
      </form>

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {jobId && (
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          <div className="rounded-2xl border border-white/8 bg-surface/40 p-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
                Timeline
              </h2>
              {running && <Spinner />}
            </div>
            <ol className="relative space-y-3 border-l border-white/10 pl-5">
              <AnimatePresence>
                {events.map((ev) => (
                  <motion.li
                    key={ev.event_id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                  >
                    <span className="absolute -left-[23px] top-1 h-3 w-3 rounded-full bg-accent" />
                    <p className="text-sm capitalize">{ev.type.replace(/_/g, " ")}</p>
                  </motion.li>
                ))}
              </AnimatePresence>
              {events.length === 0 && (
                <li className="text-sm text-muted">Waiting for events…</li>
              )}
            </ol>
          </div>
          <div className="rounded-2xl border border-white/8 bg-surface/40 p-6">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">
              Report {report?.is_partial && "(partial)"}
            </h2>
            {report ? (
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {report.text || "No report text."}
              </p>
            ) : (
              <p className="text-sm text-muted">Appears when research completes.</p>
            )}
          </div>
        </div>
      )}
    </Gate>
  );
}
