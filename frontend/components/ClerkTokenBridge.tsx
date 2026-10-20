"use client";

import { useEffect } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSession } from "@/components/SessionProvider";
import { setSsoToken, clearCredentials, setSsoTokenProvider } from "@/lib/auth";
import { CLERK_ENABLED, CLERK_JWT_TEMPLATE } from "@/lib/clerk";

// Keeps the backend session in sync with the Clerk session.
//
// When the user is signed in via Clerk we mint a session JWT and store it as the
// `X-SSO-Token` credential, then refresh the backend session (`getMe`). The
// backend validates the JWT via JWKS through the OIDC identity provider and
// derives a per-user private tenant (`user:<sub>`). On sign-out we clear the
// stored credential.
//
// CLERK_ENABLED is a build-time module constant, so the conditional hook usage
// below is stable across renders (the component subtree never changes shape).

function ClerkTokenSync() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { refresh } = useSession();

  // Register a fresh-token provider so every API request mints a current Clerk
  // JWT (tokens are short-lived; a stored one goes stale). Unregister on
  // sign-out / unmount.
  useEffect(() => {
    setSsoTokenProvider(async () => {
      if (!isSignedIn) return null;
      try {
        return await getToken(
          CLERK_JWT_TEMPLATE ? { template: CLERK_JWT_TEMPLATE } : undefined
        );
      } catch {
        return null;
      }
    });
    return () => setSsoTokenProvider(null);
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;

    async function sync() {
      if (!isSignedIn) {
        clearCredentials();
        return;
      }
      try {
        const token = await getToken(
          CLERK_JWT_TEMPLATE ? { template: CLERK_JWT_TEMPLATE } : undefined
        );
        if (cancelled || !token) return;
        setSsoToken(token);
        await refresh();
      } catch {
        // Token mint failed — leave credentials as-is.
      }
    }

    void sync();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  return null;
}

export function ClerkTokenBridge() {
  if (!CLERK_ENABLED) return null;
  return <ClerkTokenSync />;
}
