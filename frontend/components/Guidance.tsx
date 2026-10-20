"use client";

import Link from "next/link";

/** A prominent callout shown when the user's corpus is empty, pointing them to
 * the Documents page. Used on Search / Answer / Research so a new user always
 * knows the first step. */
export function EmptyCorpusNotice({
  action = "search",
}: {
  action?: string;
}) {
  return (
    <div className="rounded-2xl border border-accent/20 bg-accent/5 p-6">
      <div className="flex items-start gap-4">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent/15 text-xl text-accent">
          ①
        </div>
        <div className="min-w-0">
          <h3 className="font-semibold">Add a document first</h3>
          <p className="mt-1 text-sm text-muted">
            Your corpus is empty, so there&apos;s nothing to {action} yet.
            Upload a file (PDF, DOCX, TXT) or paste text, then come back here.
            Everything you add stays private to your account.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href="/app/documents"
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-[#04141a] transition hover:scale-[1.02]"
            >
              Add a document →
            </Link>
            <Link
              href="/app/web"
              className="rounded-lg border border-white/15 px-4 py-2 text-sm transition hover:border-accent hover:text-accent"
            >
              Or fetch a web page
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

/** A short helper line under a page title explaining what the page does and how
 * it fits the overall flow. */
export function PageHint({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-sm text-muted">{children}</p>;
}

/** A subtle inline tip (e.g. example queries) to lower the blank-page barrier. */
export function ExampleChips({
  examples,
  onPick,
}: {
  examples: string[];
  onPick: (value: string) => void;
}) {
  if (examples.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted">Try:</span>
      {examples.map((ex) => (
        <button
          key={ex}
          type="button"
          onClick={() => onPick(ex)}
          className="rounded-full border border-white/10 px-3 py-1 text-xs text-muted transition hover:border-accent hover:text-accent"
        >
          {ex}
        </button>
      ))}
    </div>
  );
}
