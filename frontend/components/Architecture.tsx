"use client";

import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { usePrefersReducedMotion } from "@/lib/useReducedMotion";

const layers = [
  {
    id: "ingest",
    label: "Ingest",
    radius: 110,
    color: "#7b61ff",
    components: ["Crawler", "Cleaner", "Embeddings", "Kafka pipeline (optional)", "Indexer"],
  },
  {
    id: "query",
    label: "Query",
    radius: 180,
    color: "#00d4ff",
    components: ["Retriever (kNN + BM25)", "RRF fusion", "Answer engine", "Research agent"],
  },
  {
    id: "edge",
    label: "Edge",
    radius: 250,
    color: "#3ad6a0",
    components: ["API gateway", "Rate limiter", "Auth", "MCP server", "SSE streaming"],
  },
];

export function Architecture() {
  const root = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<string | null>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    gsap.registerPlugin(ScrollTrigger);
    const ctx = gsap.context(() => {
      gsap.from(".arch-ring", {
        scrollTrigger: { trigger: root.current, start: "top 70%" },
        scale: 0.5,
        opacity: 0,
        duration: 0.9,
        stagger: 0.18,
        ease: "back.out(1.5)",
      });
      gsap.to(".arch-particle", {
        scrollTrigger: { trigger: root.current, start: "top 70%" },
        rotate: 360,
        duration: 18,
        repeat: -1,
        ease: "none",
        transformOrigin: "center center",
      });
    }, root);
    return () => ctx.revert();
  }, [reduced]);

  return (
    <section ref={root} className="px-5 py-24">
      <div className="mx-auto max-w-5xl">
        <h2 className="text-center text-3xl font-bold sm:text-4xl">
          How it <span className="text-gradient">works</span>
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-center text-muted">
          Documents are first pulled in by the{" "}
          <span className="text-[#7b61ff]">ingest</span> plane, made searchable
          by the <span className="text-[#00d4ff]">query</span> plane, and served
          to clients through the <span className="text-[#3ad6a0]">edge</span>.
          Hover a ring to reveal its components.
        </p>

        <div className="mt-14 grid items-center gap-10 lg:grid-cols-2">
          {/* Diagram */}
          <div className="relative mx-auto grid h-[540px] w-full max-w-[540px] place-items-center">
            <svg
              viewBox="0 0 540 540"
              className="absolute inset-0 h-full w-full"
              aria-hidden
            >
              {layers
                .slice()
                .reverse()
                .map((l) => (
                  <g key={l.id} className="arch-ring">
                    <circle
                      cx={270}
                      cy={270}
                      r={l.radius}
                      fill="none"
                      stroke={l.color}
                      strokeWidth={active === l.id ? 3 : 1.5}
                      strokeOpacity={active && active !== l.id ? 0.2 : 0.7}
                      className="cursor-pointer transition-all duration-300"
                      onMouseEnter={() => setActive(l.id)}
                      onMouseLeave={() => setActive(null)}
                    />
                    <circle
                      className="arch-particle"
                      cx={270}
                      cy={270 - l.radius}
                      r={4}
                      fill={l.color}
                    />
                  </g>
                ))}
            </svg>

            {layers.map((l) => (
              <span
                key={l.id}
                onMouseEnter={() => setActive(l.id)}
                onMouseLeave={() => setActive(null)}
                style={{
                  transform: `translateY(${-l.radius + 16}px)`,
                  color: l.color,
                }}
                className="absolute cursor-pointer text-xs font-semibold uppercase tracking-widest"
              >
                {l.label}
              </span>
            ))}

            <div className="grid h-20 w-20 place-items-center rounded-full bg-accent/15 text-center text-xs font-bold text-accent">
              Veri<br />search
            </div>
          </div>

          {/* Detail panel */}
          <div className="space-y-3">
            {layers.map((l, i) => (
                <div
                  key={l.id}
                  onMouseEnter={() => setActive(l.id)}
                  onMouseLeave={() => setActive(null)}
                  className={`glass rounded-xl p-5 transition-all duration-300 ${
                    active === l.id ? "ring-1" : "opacity-80"
                  }`}
                  style={{
                    boxShadow:
                      active === l.id ? `0 0 0 1px ${l.color}55` : undefined,
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold"
                      style={{ background: `${l.color}22`, color: l.color }}
                    >
                      {i + 1}
                    </span>
                    <h3 className="font-semibold">{l.label} layer</h3>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {l.components.map((c) => (
                      <span
                        key={c}
                        className="rounded-md border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-muted"
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </section>
  );
}
