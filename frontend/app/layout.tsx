import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { ToastProvider } from "@/components/Toast";
import { SessionProvider } from "@/components/SessionProvider";
import { ClerkTokenBridge } from "@/components/ClerkTokenBridge";
import { CLERK_ENABLED, CLERK_PUBLISHABLE_KEY } from "@/lib/clerk";

export const metadata: Metadata = {
  title: "Verisearch — AI Search with Verifiable Citations",
  description:
    "Agentic research search engine: neural + keyword hybrid retrieval, AI answers with verifiable citations, and multi-hop research.",
  metadataBase: new URL("https://verisearch-production.up.railway.app"),
  openGraph: {
    title: "Verisearch — AI Search with Verifiable Citations",
    description:
      "Neural + keyword hybrid retrieval, AI answers with verifiable citations, and multi-hop research.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const shell = (
    <html lang="en">
      <body className="min-h-screen bg-base text-[#e8e8f0] antialiased">
        <SessionProvider>
          <ClerkTokenBridge />
          <ToastProvider>
            <Nav />
            <main>{children}</main>
            <footer className="border-t border-white/5 py-8 text-center text-sm text-muted">
              <p>
                Verisearch · open source ·{" "}
                <a
                  href="https://github.com/malaythakur/verisearch"
                  className="text-accent hover:underline"
                >
                  GitHub
                </a>{" "}
                ·{" "}
                <a
                  href="https://verisearch-production.up.railway.app/docs"
                  className="text-accent hover:underline"
                >
                  API Docs
                </a>
              </p>
            </footer>
          </ToastProvider>
        </SessionProvider>
      </body>
    </html>
  );

  // Only mount ClerkProvider when a publishable key is configured. This lets the
  // app run locally / in CI without Clerk credentials, falling back to the
  // manual token paste flow.
  if (CLERK_ENABLED) {
    return (
      <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>
        {shell}
      </ClerkProvider>
    );
  }
  return shell;
}
