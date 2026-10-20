// Client-side credential handling for the enterprise shell.
//
// Two auth planes mirror the backend:
//  - SSO (human): an OIDC token presented via the X-SSO-Token header. In a real
//    deployment this is set by the OIDC redirect callback; here it can be pasted
//    for demos.
//  - API key (machine): a Bearer token.
//
// Credentials are kept in localStorage (browser-only). UI gating is convenience;
// the server is the source of truth for authorization.

const SSO_KEY = "verisearch_sso_token";
const API_KEY = "verisearch_api_key";

export type CredentialKind = "sso" | "apikey" | "none";

export function getCredential(): { kind: CredentialKind; value: string } {
  if (typeof window === "undefined") return { kind: "none", value: "" };
  const sso = window.localStorage.getItem(SSO_KEY);
  if (sso) return { kind: "sso", value: sso };
  const key = window.localStorage.getItem(API_KEY);
  if (key) return { kind: "apikey", value: key };
  return { kind: "none", value: "" };
}

export function setSsoToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SSO_KEY, token);
  window.localStorage.removeItem(API_KEY);
}

export function setApiKey(key: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(API_KEY, key);
  window.localStorage.removeItem(SSO_KEY);
}

export function clearCredentials(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SSO_KEY);
  window.localStorage.removeItem(API_KEY);
}

/** Build the auth headers for the current credential. */
export function authHeaders(): Record<string, string> {
  const cred = getCredential();
  if (cred.kind === "sso") return { "X-SSO-Token": cred.value };
  if (cred.kind === "apikey") return { Authorization: `Bearer ${cred.value}` };
  return {};
}

// --- Fresh-token provider (Clerk) ---------------------------------------
//
// Clerk session JWTs are short-lived. Reading a token stored once at sign-in
// goes stale and breaks the session. To avoid that, the Clerk bridge registers
// an async provider here that mints a fresh token on demand. The API layer
// calls `getAuthHeaders()` (async) before each request so every call carries a
// valid token. When no provider is registered we fall back to the stored
// credential (manual SSO-token / API-key flow).

type TokenProvider = () => Promise<string | null>;

let ssoTokenProvider: TokenProvider | null = null;

export function setSsoTokenProvider(provider: TokenProvider | null): void {
  ssoTokenProvider = provider;
}

/** Async variant of authHeaders that mints a fresh SSO token when a provider
 * (Clerk) is registered. Falls back to the stored credential otherwise. */
export async function getAuthHeaders(): Promise<Record<string, string>> {
  if (ssoTokenProvider) {
    try {
      const fresh = await ssoTokenProvider();
      if (fresh) {
        // Keep localStorage in sync so getMe()/SessionProvider see a value too.
        setSsoToken(fresh);
        return { "X-SSO-Token": fresh };
      }
    } catch {
      // Fall through to stored credential on mint failure.
    }
  }
  return authHeaders();
}
