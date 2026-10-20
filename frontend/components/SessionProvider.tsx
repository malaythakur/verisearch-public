"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getMe } from "@/lib/api";
import { clearCredentials, getCredential } from "@/lib/auth";
import type { MeResponse } from "@/lib/types";

interface SessionState {
  me: MeResponse | null;
  loading: boolean;
  error: string | null;
  signedIn: boolean;
  refresh: () => Promise<void>;
  signOut: () => void;
}

const SessionContext = createContext<SessionState>({
  me: null,
  loading: true,
  error: null,
  signedIn: false,
  refresh: async () => {},
  signOut: () => {},
});

export function useSession() {
  return useContext(SessionContext);
}

/** Convenience hook for RBAC-aware rendering (Req 13.2/13.3). */
export function usePermissions() {
  const { me } = useSession();
  const perms = new Set(me?.permissions ?? []);
  const roles = new Set(me?.roles ?? []);
  return {
    has: (permission: string) => perms.has(permission),
    hasRole: (role: string) => roles.has(role),
    permissions: me?.permissions ?? [],
    roles: me?.roles ?? [],
  };
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const cred = getCredential();
    if (cred.kind === "none") {
      setMe(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getMe();
      setMe(data);
    } catch (e) {
      setMe(null);
      setError(e instanceof Error ? e.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  }, []);

  const signOut = useCallback(() => {
    clearCredentials();
    setMe(null);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <SessionContext.Provider
      value={{ me, loading, error, signedIn: me !== null, refresh, signOut }}
    >
      {children}
    </SessionContext.Provider>
  );
}
