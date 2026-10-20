"use client";

import { motion } from "framer-motion";
import Link from "next/link";

const features = [
  {
    title: "Hybrid retrieval",
    desc: "Neural kNN, BM25 keyword, and RRF-fused hybrid search over your indexed docs.",
    href: "/search",
    icon: "⌕",
  },
  {
    title: "Cited answers",
    desc: "Streaming AI answers grounded in sources with span-level, verifiable citations.",
    href: "/answer",
    icon: "✶",
  },
  {
    title: "Index anything",
    desc: "Push a URL + content and it is cleaned, embedded, and searchable in seconds.",
    href: "/index-doc",
    icon: "＋",
  },
  {
    title: "Multi-hop research",
    desc: "Launch a research goal and watch the agent plan and execute step by step.",
    href: "/research",
    icon: "◈",
  },
  {
    title: "Programmable pipelines",
    desc: "Compose filters, rerankers, and transforms into reusable retrieval pipelines.",
    href: "/pipelines",
    icon: "⚙",
  },
  {
    title: "MCP + API first",
    desc: "Use it from Claude Desktop, custom agents, or any HTTP client. OpenAPI docs included.",
    href: "https://verisearch-production.up.railway.app/docs",
    icon: "⚡",
  },
];

export function FeatureGrid() {
  return (
    <section className="px-5 py-16">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.4, delay: i * 0.06 }}
            >
              <Link
                href={f.href}
                className="group block h-full rounded-2xl border border-white/8 bg-surface/40 p-6 transition-all hover:border-accent/40 hover:bg-surface"
              >
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-accent/15 text-xl text-accent">
                  {f.icon}
                </div>
                <h3 className="mt-4 text-lg font-semibold group-hover:text-accent">
                  {f.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  {f.desc}
                </p>
              </Link>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
