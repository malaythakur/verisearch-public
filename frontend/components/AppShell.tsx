"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession, usePermissions } from "@/components/SessionProvider";
import { SignOutButton } from "@/components/SignOutButton";

interface NavItem {
  href: string;
  label: string;
  permission?: string; // required permission to show
  role?: string; // required role to show
}

const NAV: NavItem[] = [
  { href: "/app", label: "Overview" },
  { href: "/app/search", label: "Search", permission: "search" },
  { href: "/app/web", label: "Web Fetch", permission: "search" },
  { href: "/app/answer", label: "Answers", permission: "answer" },
  { href: "/app/documents", label: "Documents", permission: "index" },
  { href: "/app/research", label: "Research", permission: "research" },
  { href: "/app/keys", label: "API Keys", role: "org_admin" },
  { href: "/app/usage", label: "Usage" },
  { href: "/app/audit", label: "Audit", permission: "audit:read" },
  { href: "/app/admin", label: "Admin", role: "org_admin" },
  { href: "/app/settings", label: "Data & Settings", role: "org_admin" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, signedIn } = useSession();
  const { has, hasRole } = usePermissions();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !signedIn) router.replace("/login");
  }, [loading, signedIn, router]);

  if (loading) {
    return (
      <div className="grid min-h-[60vh] place-items-center text-muted">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }
  if (!signedIn || !me) return null;

  const visible = NAV.filter((item) => {
    if (item.permission && !has(item.permission)) return false;
    if (item.role && !hasRole(item.role)) return false;
    return true;
  });

  return (
    <div className="mx-auto flex max-w-7xl gap-6 px-4 py-6">
      {/* Sidebar */}
      <aside className="hidden w-56 shrink-0 lg:block">
        <nav className="sticky top-20 space-y-1">
          {visible.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded-lg px-3 py-2 text-sm transition ${
                  active
                    ? "bg-accent/15 text-accent"
                    : "text-muted hover:bg-white/5 hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main */}
      <div className="min-w-0 flex-1">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/8 bg-surface/40 px-4 py-3">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium">{me.subject}</span>
            <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs text-muted">
              {me.roles.join(", ") || "no roles"}
            </span>
            <span
              className={`rounded-md px-2 py-0.5 text-xs ${
                me.auth_kind === "human"
                  ? "bg-emerald-500/10 text-emerald-300"
                  : "bg-amber-500/10 text-amber-300"
              }`}
            >
              {me.auth_kind === "human" ? "SSO" : "API key"}
            </span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span title="Deployment mode">
              mode: <span className="text-accent">{me.deployment_mode}</span>
            </span>
            <span title="Data residency region">
              region: <span className="text-accent">{me.data_residency_region}</span>
            </span>
            <SignOutButton />
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Wrap a page section in a permission gate (UI convenience; server enforces). */
export function Gate({
  permission,
  role,
  children,
}: {
  permission?: string;
  role?: string;
  children: React.ReactNode;
}) {
  const { has, hasRole } = usePermissions();
  const allowed =
    (!permission || has(permission)) && (!role || hasRole(role));
  if (!allowed) {
    return (
      <div className="rounded-xl border border-white/10 bg-surface/40 p-10 text-center text-muted">
        You don&apos;t have permission to view this. Contact your org admin.
      </div>
    );
  }
  return <>{children}</>;
}
