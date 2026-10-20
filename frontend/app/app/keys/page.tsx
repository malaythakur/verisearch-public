"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Gate } from "@/components/AppShell";
import { useToast } from "@/components/Toast";

interface ApiKeyRow {
  id: string;
  name: string;
  prefix: string;
  createdAt: string;
}

// Generates a demo key client-side. In production this calls a backend
// key-management endpoint which returns the full secret exactly once.
function generateKey(): { full: string; prefix: string } {
  const prefix = "vsk_" + Math.random().toString(36).slice(2, 8);
  const secret = Array.from(crypto.getRandomValues(new Uint8Array(24)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return { full: `${prefix}_${secret}`, prefix };
}

export default function KeysPage() {
  const toast = useToast();
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [name, setName] = useState("");
  const [revealed, setRevealed] = useState<string | null>(null);

  function create() {
    if (!name.trim()) return;
    const { full, prefix } = generateKey();
    const row: ApiKeyRow = {
      id: crypto.randomUUID(),
      name: name.trim(),
      prefix,
      createdAt: new Date().toISOString(),
    };
    setKeys((k) => [row, ...k]);
    setRevealed(full); // shown exactly once
    setName("");
  }

  function revoke(id: string) {
    setKeys((k) => k.filter((x) => x.id !== id));
    toast("API key revoked", "success");
  }

  return (
    <Gate role="org_admin">
      <h1 className="text-2xl font-bold">API Keys</h1>
      <p className="mt-1 text-muted">
        Tenant-scoped machine credentials. The full secret is shown once on creation.
      </p>

      <div className="mt-5 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Key name (e.g. ci-pipeline)"
          className="flex-1 rounded-lg border border-white/10 bg-surface px-4 py-2.5 outline-none ring-accent/40 focus:ring-2"
        />
        <button
          onClick={create}
          disabled={!name.trim()}
          className="rounded-lg bg-accent px-5 py-2.5 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
        >
          Create key
        </button>
      </div>

      <AnimatePresence>
        {revealed && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4 overflow-hidden rounded-lg border border-amber-500/40 bg-amber-500/10 p-4"
          >
            <p className="text-sm font-medium text-amber-300">
              Copy this key now — it won&apos;t be shown again.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 break-all rounded bg-base/60 px-3 py-2 font-mono text-xs">
                {revealed}
              </code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(revealed);
                  toast("Copied to clipboard", "success");
                }}
                className="rounded-md border border-white/15 px-3 py-2 text-sm transition hover:border-accent hover:text-accent"
              >
                Copy
              </button>
              <button
                onClick={() => setRevealed(null)}
                className="rounded-md px-3 py-2 text-sm text-muted hover:text-white"
              >
                Done
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-6 rounded-xl border border-white/8 bg-surface/40">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-muted">
            <tr className="border-b border-white/8">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Prefix</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {keys.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted">
                  No API keys yet.
                </td>
              </tr>
            ) : (
              keys.map((k) => (
                <tr key={k.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {k.prefix}_••••••••
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {new Date(k.createdAt).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => revoke(k.id)}
                      className="text-xs text-red-400 hover:underline"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-muted">
        Note: key management is a UI surface here; wiring it to a backend
        key-issuance endpoint (Argon2id-hashed, prefix-indexed) is tracked separately.
      </p>
    </Gate>
  );
}
