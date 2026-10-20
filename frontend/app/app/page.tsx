"use client";

import Link from "next/link";
import { useSession, usePermissions } from "@/components/SessionProvider";
import { useCorpus } from "@/lib/useCorpus";

const CARDS = [
  { href: "/app/documents", label: "Documents", desc: "Index and manage source documents", perm: "index" },
  { href: "/app/web", label: "Web Fetch", desc: "Retrieve live web pages via the crawler", perm: "search" },
  { href: "/app/search", label: "Search", desc: "Hybrid retrieval over your corpus", perm: "search" },
  { href: "/app/answer", label: "Cited Answers", desc: "AI answers with verifiable citations", perm: "answer" },
  { href: "/app/research", label: "Research", desc: "Multi-hop research jobs", perm: "research" },
  { href: "/app/keys", label: "API Keys", desc: "Create and revoke tenant keys", role: "org_admin" },
  { href: "/app/audit", label: "Audit Log", desc: "Tamper-evident audit + SIEM export", perm: "audit:read" },
];

interface Step {
  n: number;
  title: string;
  desc: string;
  href: string;
  cta: string;
}

export default function OverviewPage() {
  const { me } = useSession();
  const { has, hasRole } = usePermissions();
  const { isEmpty, count, loading } = useCorpus();

  const cards = CARDS.filter(
    (c) => (!c.perm || has(c.perm)) && (!c.role || hasRole(c.role))
  );

  const steps: Step[] = [
    {
      n: 1,
      title: "Add your documents",
      desc: "Upload files (PDF, DOCX, TXT) or paste text. This builds your private corpus — only you can see it.",
      href: "/app/documents",
      cta: "Add documents",
    },
    {
      n: 2,
      title: "Search or ask questions",
      desc: "Run a hybrid search, or ask a question and get an answer with citations that link back to your sources.",
      href: "/app/answer",
      cta: "Ask a question",
    },
    {
      n: 3,
      title: "Run deep research",
      desc: "Kick off a multi-hop research job that reasons across your corpus and produces a structured report.",
      href: "/app/research",
      cta: "Start research",
    },
  ];

  // Which step is "current" — drives the highlight.
  const currentStep = isEmpty ? 1 : 2;

  return (
    <div>
      <h1 className="text-2xl font-bold">
        Welcome{me ? `, ${me.subject}` : ""}
      </h1>
      <p className="mt-1 text-muted">
        This is your private workspace. Documents you add stay isolated to your
        account
        {me?.tenant_id ? (
          <>
            {" "}
            (<span className="font-mono text-accent">{me.tenant_id}</span>)
          </>
        ) : null}
        .
      </p>

      {/* Getting started flow */}
      <div className="mt-6 rounded-2xl border border-white/8 bg-surface/40 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
            Getting started
          </h2>
          {!loading && (
            <span className="text-xs text-muted">
              {count} document{count === 1 ? "" : "s"} in your corpus
            </span>
          )}
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {steps.map((s) => {
            const done = s.n < currentStep;
            const active = s.n === currentStep;
            return (
              <div
                key={s.n}
                className={`rounded-xl border p-4 transition ${
                  active
                    ? "border-accent/40 bg-accent/5"
                    : "border-white/8 bg-base/40"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`grid h-7 w-7 place-items-center rounded-full text-sm font-semibold ${
                      done
                        ? "bg-emerald-500/15 text-emerald-300"
                        : active
                        ? "bg-accent/20 text-accent"
                        : "bg-white/5 text-muted"
                    }`}
                  >
                    {done ? "✓" : s.n}
                  </span>
                  <h3 className="font-semibold">{s.title}</h3>
                </div>
                <p className="mt-2 text-sm text-muted">{s.desc}</p>
                <Link
                  href={s.href}
                  className={`mt-3 inline-block text-sm font-medium ${
                    active ? "text-accent hover:underline" : "text-muted hover:text-white"
                  }`}
                >
                  {s.cta} →
                </Link>
              </div>
            );
          })}
        </div>

        {isEmpty && (
          <p className="mt-4 text-sm text-accent">
            Start with step 1 — add a document so Search, Answers, and Research
            have something to work with.
          </p>
        )}
      </div>

      {/* Feature shortcuts */}
      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wider text-muted">
        All features
      </h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="rounded-xl border border-white/8 bg-surface/40 p-5 transition hover:border-accent/40 hover:bg-surface"
          >
            <h3 className="font-semibold">{c.label}</h3>
            <p className="mt-1 text-sm text-muted">{c.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
