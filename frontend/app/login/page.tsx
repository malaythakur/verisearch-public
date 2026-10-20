"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { setApiKey, setSsoToken } from "@/lib/auth";
import { useSession } from "@/components/SessionProvider";
import { API_BASE } from "@/lib/api";
import { CLERK_ENABLED } from "@/lib/clerk";
import { ClerkLogin } from "@/components/ClerkLogin";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [mode, setMode] = useState<"sso" | "apikey">("sso");
  const [tokenInput, setTokenInput] = useState("");
  const [busy, setBusy] = useState(false);

  // In a real deployment the SSO button redirects to the tenant's IdP and the
  // callback sets the token. For the demo, an OIDC token can be pasted.
  async function signInSso() {
    if (!tokenInput.trim()) return;
    setBusy(true);
    setSsoToken(tokenInput.trim());
    await refresh();
    router.push("/app");
  }

  async function signInApiKey() {
    if (!tokenInput.trim()) return;
    setBusy(true);
    setApiKey(tokenInput.trim());
    await refresh();
    router.push("/app");
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center px-5">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-2xl border border-white/8 bg-surface/50 p-8"
      >
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-accent/15 text-2xl text-accent">
            ◎
          </div>
          <h1 className="text-2xl font-bold">
            Sign in to Veri<span className="text-accent">search</span>
          </h1>
          <p className="mt-1 text-sm text-muted">
            {CLERK_ENABLED
              ? "Sign in with Google to build your private corpus."
              : "Enterprise access via your identity provider."}
          </p>
        </div>

        {CLERK_ENABLED ? (
          <ClerkLogin />
        ) : (
          <>
            <div className="mb-5 flex rounded-lg border border-white/10 p-1 text-sm">
              <button
                onClick={() => setMode("sso")}
                className={`flex-1 rounded-md px-3 py-2 transition ${
                  mode === "sso" ? "bg-accent/15 text-accent" : "text-muted"
                }`}
              >
                Company SSO
              </button>
              <button
                onClick={() => setMode("apikey")}
                className={`flex-1 rounded-md px-3 py-2 transition ${
                  mode === "apikey" ? "bg-accent/15 text-accent" : "text-muted"
                }`}
              >
                API key
              </button>
            </div>

            {mode === "sso" ? (
              <div className="space-y-3">
                <button
                  onClick={() => {
                    alert(
                      "In production this redirects to your IdP (Okta/Entra/Auth0).\n" +
                        "For this demo, paste an OIDC token below."
                    );
                  }}
                  className="w-full rounded-lg bg-accent px-4 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02]"
                >
                  Sign in with your company IdP →
                </button>
                <p className="text-center text-xs text-muted">No password — OIDC / SAML only.</p>
                <textarea
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  rows={3}
                  placeholder="Demo: paste an OIDC ID token"
                  className="w-full resize-none rounded-lg border border-white/10 bg-base px-3 py-2 font-mono text-xs outline-none ring-accent/40 focus:ring-2"
                />
                <button
                  onClick={signInSso}
                  disabled={busy || !tokenInput.trim()}
                  className="w-full rounded-lg border border-white/15 px-4 py-2 text-sm transition hover:border-accent hover:text-accent disabled:opacity-40"
                >
                  Use token
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                <input
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Bearer API key (prefix_secret)"
                  className="w-full rounded-lg border border-white/10 bg-base px-3 py-3 font-mono text-sm outline-none ring-accent/40 focus:ring-2"
                />
                <button
                  onClick={signInApiKey}
                  disabled={busy || !tokenInput.trim()}
                  className="w-full rounded-lg bg-accent px-4 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
                >
                  Continue with API key
                </button>
                <p className="text-center text-xs text-muted">
                  Machine clients use a tenant-scoped API key.
                </p>
              </div>
            )}
          </>
        )}
      </motion.div>
      <p className="mt-4 text-center text-xs text-muted">
        Connects to <span className="font-mono">{API_BASE}</span>
      </p>
    </div>
  );
}
