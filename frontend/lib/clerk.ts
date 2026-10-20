// Clerk integration flags.
//
// Clerk is the human sign-in plane (Google login). It issues a session JWT that
// the backend validates via JWKS through the existing OIDC identity provider.
// The JWT is fed into the existing `X-SSO-Token` header (see lib/auth.ts), so no
// backend auth code changes are required — Clerk is purely the *token source*.
//
// When no publishable key is configured the whole Clerk layer is bypassed and
// the app falls back to the manual SSO-token / API-key paste flow. This keeps
// local development working without Clerk credentials.

export const CLERK_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";

export const CLERK_ENABLED = CLERK_PUBLISHABLE_KEY.length > 0;

// Optional JWT template name. Create a template in the Clerk dashboard whose
// audience matches the backend `oidc_audience`. If unset, the default Clerk
// session token is used.
export const CLERK_JWT_TEMPLATE =
  process.env.NEXT_PUBLIC_CLERK_JWT_TEMPLATE ?? "";
