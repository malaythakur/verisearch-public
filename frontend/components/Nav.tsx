"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { useSession } from "@/components/SessionProvider";

const links = [
  { href: "/", label: "Home" },
];

export function Nav() {
  const pathname = usePathname();
  const { signedIn } = useSession();

  return (
    <header className="sticky top-0 z-50 border-b border-white/5 bg-base/70 backdrop-blur-md">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-accent">
            ◎
          </span>
          <span className="text-lg font-bold tracking-tight">
            Veri<span className="text-accent">search</span>
          </span>
        </Link>
        <ul className="flex items-center gap-1 text-sm">
          {links.map((l) => {
            const active = pathname === l.href;
            return (
              <li key={l.href} className="relative">
                <Link
                  href={l.href}
                  className={`rounded-md px-3 py-2 transition-colors ${
                    active ? "text-accent" : "text-muted hover:text-white"
                  }`}
                >
                  {l.label}
                  {active && (
                    <motion.span
                      layoutId="nav-underline"
                      className="absolute inset-x-2 -bottom-px h-px bg-accent"
                    />
                  )}
                </Link>
              </li>
            );
          })}
          <li>
            <Link
              href={signedIn ? "/app" : "/login"}
              className="ml-2 rounded-lg bg-accent px-3 py-2 font-semibold text-[#04141a] transition hover:scale-[1.03]"
            >
              {signedIn ? "Console" : "Sign in"}
            </Link>
          </li>
        </ul>
      </nav>
    </header>
  );
}
