"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import gsap from "gsap";
import { usePrefersReducedMotion } from "@/lib/useReducedMotion";

export function Hero() {
  const root = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.from(".hero-eyebrow", { y: 16, opacity: 0, duration: 0.5 })
        .from(
          ".hero-line",
          { y: 28, opacity: 0, duration: 0.7, stagger: 0.12 },
          "-=0.2"
        )
        .from(".hero-sub", { y: 18, opacity: 0, duration: 0.6 }, "-=0.3")
        .from(
          ".hero-cta",
          {
            y: 14,
            opacity: 0,
            duration: 0.5,
            stagger: 0.1,
            clearProps: "transform",
          },
          "-=0.3"
        )
        .from(".hero-glow", { scale: 0.6, opacity: 0, duration: 1.2 }, 0);
    }, root);
    return () => ctx.revert();
  }, [reduced]);

  return (
    <section
      ref={root}
      className="relative overflow-hidden px-5 pb-24 pt-20 sm:pt-28"
    >
      <div className="hero-glow pointer-events-none absolute left-1/2 top-24 h-[420px] w-[620px] -translate-x-1/2 rounded-full bg-accent/20 blur-[120px]" />
      <div className="relative mx-auto max-w-4xl text-center">
        <span className="hero-eyebrow inline-block rounded-full border border-accent/30 bg-accent/10 px-4 py-1 text-xs font-medium uppercase tracking-widest text-accent">
          Agentic Research Search Engine
        </span>
        <h1 className="mt-6 text-balance text-5xl font-extrabold leading-[1.05] tracking-tight sm:text-7xl">
          <span className="hero-line block">AI Search with</span>
          <span className="hero-line block text-gradient">
            Verifiable Citations
          </span>
        </h1>
        <p className="hero-sub mx-auto mt-6 max-w-2xl text-lg text-muted">
          Neural + keyword hybrid retrieval, streaming answers grounded in
          sources you can verify span-by-span, and multi-hop research that shows
          its work.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link
            href="/app/answer"
            className="hero-cta inline-flex items-center justify-center rounded-lg border border-transparent bg-accent px-6 py-3 text-base font-semibold text-[#04141a] shadow-glow transition-transform hover:scale-[1.03]"
          >
            Try an answer →
          </Link>
          <Link
            href="/app/search"
            className="hero-cta inline-flex items-center justify-center rounded-lg border border-white/20 bg-white/5 px-6 py-3 text-base font-semibold text-white backdrop-blur-sm transition-colors hover:border-accent hover:bg-accent/10 hover:text-accent"
          >
            Search the index
          </Link>
        </div>
      </div>
    </section>
  );
}
