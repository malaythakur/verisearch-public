"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { SignInButton, SignedIn, SignedOut, useAuth } from "@clerk/nextjs";
import { useSession } from "@/components/SessionProvider";

// Google sign-in via Clerk. Clerk handles the OAuth round-trip; the
// ClerkTokenBridge then mints a session JWT and feeds it into the backend
// session. We only forward to the console once the BACKEND session is
// established (useSession().signedIn) — never on Clerk's own signed-in state.
// This prevents a redirect loop when the backend has not yet validated the
// token (e.g. IDP_KIND=none or JWT template missing).
//
// This component is only rendered when CLERK_ENABLED is true, so the Clerk
// provider context is guaranteed to be present.
export function ClerkLogin() {
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  const { signedIn, loading, error } = useSession();

  useEffect(() => {
    if (signedIn) router.push("/app");
  }, [signedIn, router]);

  // Clerk says signed in, but the backend session is still resolving or failed.
  const clerkSignedInBackendPending = isLoaded && isSignedIn && !signedIn;

  return (
    <div className="space-y-3">
      <SignedOut>
        <SignInButton mode="modal" forceRedirectUrl="/login">
          <button className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02]">
            Continue with Google →
          </button>
        </SignInButton>
        <p className="text-center text-xs text-muted">
          No password — your documents stay private to your account.
        </p>
      </SignedOut>

      <SignedIn>
        {clerkSignedInBackendPending ? (
          <div className="space-y-2 text-center">
            {loading ? (
              <p className="text-sm text-muted">
                <span className="mr-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent align-middle" />
                Completing sign-in…
              </p>
            ) : (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-left text-xs text-amber-200">
                Signed in with Google, but the backend rejected the session
                {error ? `: ${error}` : "."} This usually means the server-side
                Clerk validation isn&apos;t enabled yet (IDP_KIND / JWT template).
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => router.push("/app")}
            className="w-full rounded-lg bg-accent px-4 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02]"
          >
            Go to console →
          </button>
        )}
      </SignedIn>
    </div>
  );
}
