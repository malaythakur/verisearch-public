import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Clerk is mounted only when a publishable key is configured. Without keys the
// middleware is a pass-through so the app runs locally / in CI using the manual
// token-paste fallback. We read the key directly from the env here because the
// middleware runs in its own (edge) module scope.
const clerkEnabled = (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "").length > 0;

// The console lives under /app/*. These routes require a signed-in user. When
// Clerk is enabled we enforce this server-side (a redirect to /login) so the
// gated UI never renders for anonymous visitors. The marketing pages, /login,
// and legacy redirects stay public. The backend independently rejects every
// unauthenticated /v1 call, so data is protected regardless.
const isProtectedRoute = createRouteMatcher(["/app(.*)"]);

const handler = clerkEnabled
  ? clerkMiddleware(async (auth, req) => {
      if (isProtectedRoute(req)) {
        const { userId } = await auth();
        if (!userId) {
          const signIn = new URL("/login", req.url);
          return NextResponse.redirect(signIn);
        }
      }
      return NextResponse.next();
    })
  : (_req: NextRequest) => NextResponse.next();

export default handler;

export const config = {
  matcher: [
    // Skip Next internals and static files; run on everything else + API routes.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
