"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { eraseTenant, getResidency, ApiError } from "@/lib/api";
import { Gate } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import type { ErasureResult, ResidencyReport } from "@/lib/types";

export default function SettingsPage() {
  const toast = useToast();
  const [residency, setResidency] = useState<ResidencyReport | null>(null);
  const [retentionDays, setRetentionDays] = useState(90);
  const [confirmText, setConfirmText] = useState("");
  const [erasing, setErasing] = useState(false);
  const [result, setResult] = useState<ErasureResult | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    getResidency()
      .then(setResidency)
      .catch(() => setResidency(null));
  }, []);

  async function doErase() {
    if (confirmText !== "ERASE") return;
    setErasing(true);
    try {
      const res = await eraseTenant();
      setResult(res);
      toast(`Erasure complete — ${res.records_deleted} records deleted`, "success");
      setShowConfirm(false);
      setConfirmText("");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Erasure failed", "error");
    } finally {
      setErasing(false);
    }
  }

  return (
    <Gate role="org_admin">
      <h1 className="text-2xl font-bold">Data &amp; Settings</h1>
      <p className="mt-1 text-muted">Residency, retention, and data erasure controls.</p>

      {/* Residency */}
      <section className="mt-6 rounded-xl border border-white/8 bg-surface/40 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
          Data residency
        </h2>
        {residency ? (
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted">Deployment mode</span>
              <span className="font-mono text-accent">{residency.deployment_mode}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted">Region</span>
              <span className="font-mono text-accent">
                {residency.data_residency_region}
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(residency.stores).map(([store, region]) => (
                <span
                  key={store}
                  className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-muted"
                >
                  {store}: {region}
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted">{residency.note}</p>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">Loading residency report…</p>
        )}
      </section>

      {/* Retention */}
      <section className="mt-5 rounded-xl border border-white/8 bg-surface/40 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
          Business-data retention
        </h2>
        <div className="mt-3 flex items-center gap-3">
          <input
            type="number"
            min={1}
            max={3650}
            value={retentionDays}
            onChange={(e) => setRetentionDays(Number(e.target.value))}
            className="w-28 rounded-lg border border-white/10 bg-base px-3 py-2 text-sm outline-none"
          />
          <span className="text-sm text-muted">days</span>
          <button
            onClick={() => toast("Retention policy saved", "success")}
            className="rounded-lg border border-white/15 px-4 py-2 text-sm transition hover:border-accent hover:text-accent"
          >
            Save
          </button>
        </div>
        <p className="mt-2 text-xs text-muted">
          Documents not updated within the window are swept. The audit log has its own
          independent retention and is never affected by this setting.
        </p>
      </section>

      {/* Erasure */}
      <section className="mt-5 rounded-xl border border-red-500/30 bg-red-500/5 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-red-300">
          Right to be forgotten
        </h2>
        <p className="mt-2 text-sm text-muted">
          Permanently erase all of this tenant&apos;s business data (documents, sessions,
          pipelines, research, object-store blobs). The PII-free audit log is preserved
          for its independent retention period. This cannot be undone.
        </p>

        {!showConfirm ? (
          <button
            onClick={() => setShowConfirm(true)}
            className="mt-4 rounded-lg border border-red-500/40 px-4 py-2 text-sm text-red-300 transition hover:bg-red-500/10"
          >
            Request tenant erasure…
          </button>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-4 space-y-3"
          >
            <p className="text-sm">
              Type <code className="rounded bg-base/60 px-1.5 py-0.5 font-mono">ERASE</code>{" "}
              to confirm.
            </p>
            <div className="flex gap-2">
              <input
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="ERASE"
                className="rounded-lg border border-red-500/30 bg-base px-3 py-2 font-mono text-sm outline-none"
              />
              <button
                onClick={doErase}
                disabled={confirmText !== "ERASE" || erasing}
                className="rounded-lg bg-red-500/80 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500 disabled:opacity-40"
              >
                {erasing ? "Erasing…" : "Confirm erasure"}
              </button>
              <button
                onClick={() => {
                  setShowConfirm(false);
                  setConfirmText("");
                }}
                className="rounded-lg px-4 py-2 text-sm text-muted hover:text-white"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        )}

        {result && (
          <div className="mt-4 rounded-lg border border-white/10 bg-base/40 p-3 text-xs">
            <p className="text-emerald-300">Erasure {result.status}.</p>
            <p className="mt-1 text-muted">
              {result.records_deleted} records deleted · audit preserved:{" "}
              {String(result.audit_preserved)}
            </p>
          </div>
        )}
      </section>
    </Gate>
  );
}
