"use client";

import { useState } from "react";
import { exportAudit, ApiError } from "@/lib/api";
import { Gate } from "@/components/AppShell";
import { useToast } from "@/components/Toast";

interface AuditRow {
  actor?: string;
  action?: string;
  resource?: string;
  request_id?: string;
  timestamp_utc?: string;
  entry_hash?: string;
  prev_hash?: string;
  [k: string]: unknown;
}

export default function AuditPage() {
  const toast = useToast();
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actorFilter, setActorFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = (await exportAudit()) as AuditRow[];
      setRows(data);
      if (data.length === 0) toast("No audit entries for this tenant yet", "info");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load audit log");
      setRows(null);
    } finally {
      setLoading(false);
    }
  }

  function download() {
    if (!rows) return;
    const ndjson = rows.map((r) => JSON.stringify(r)).join("\n");
    const blob = new Blob([ndjson], { type: "application/x-ndjson" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `verisearch-audit-${Date.now()}.ndjson`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const filtered = (rows ?? []).filter(
    (r) =>
      (!actorFilter || (r.actor ?? "").includes(actorFilter)) &&
      (!actionFilter || (r.action ?? "").includes(actionFilter))
  );

  return (
    <Gate permission="audit:read">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Audit Log</h1>
          <p className="mt-1 text-muted">
            Tamper-evident, hash-chained. Export as NDJSON for your SIEM.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="rounded-lg border border-white/15 px-4 py-2 text-sm transition hover:border-accent hover:text-accent disabled:opacity-40"
          >
            {loading ? "Loading…" : "Load"}
          </button>
          <button
            onClick={download}
            disabled={!rows || rows.length === 0}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
          >
            Export NDJSON
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {rows && (
        <>
          <div className="mt-5 flex gap-2">
            <input
              value={actorFilter}
              onChange={(e) => setActorFilter(e.target.value)}
              placeholder="Filter by actor"
              className="rounded-lg border border-white/10 bg-surface px-3 py-2 text-sm outline-none ring-accent/40 focus:ring-2"
            />
            <input
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="Filter by action"
              className="rounded-lg border border-white/10 bg-surface px-3 py-2 text-sm outline-none ring-accent/40 focus:ring-2"
            />
            <span className="self-center text-xs text-muted">
              {filtered.length} / {rows.length} entries
            </span>
          </div>

          <div className="mt-4 overflow-x-auto rounded-xl border border-white/8 bg-surface/40">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-muted">
                <tr className="border-b border-white/8">
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Action</th>
                  <th className="px-4 py-3">Resource</th>
                  <th className="px-4 py-3">Chain</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={i} className="border-b border-white/5 last:border-0">
                    <td className="px-4 py-3 text-xs text-muted">
                      {r.timestamp_utc
                        ? new Date(r.timestamp_utc).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-4 py-3">{r.actor ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-white/5 px-2 py-0.5 text-xs">
                        {r.action ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">
                      {r.resource ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-[10px] text-muted">
                      {typeof r.entry_hash === "string"
                        ? r.entry_hash.slice(0, 10) + "…"
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!rows && !error && (
        <div className="mt-6 rounded-xl border border-white/10 bg-surface/40 p-10 text-center text-muted">
          Click Load to fetch this tenant&apos;s audit log.
        </div>
      )}
    </Gate>
  );
}
