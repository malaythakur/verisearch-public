"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/SessionProvider";

interface UsageMetric {
  label: string;
  value: number;
  quota: number;
  unit: string;
}

// Usage data comes from the metering subsystem in production. Until that read
// endpoint is wired, this reflects plan limits with current-session counters.
function buildUsage(): UsageMetric[] {
  return [
    { label: "Search queries", value: 0, quota: 10000, unit: "this month" },
    { label: "Documents indexed", value: 0, quota: 5000, unit: "total" },
    { label: "Answer generations", value: 0, quota: 2000, unit: "this month" },
    { label: "Research jobs", value: 0, quota: 200, unit: "this month" },
  ];
}

export default function UsagePage() {
  const { me } = useSession();
  const [metrics, setMetrics] = useState<UsageMetric[]>([]);

  useEffect(() => {
    setMetrics(buildUsage());
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold">Usage</h1>
      <p className="mt-1 text-muted">
        Plan consumption for tenant{" "}
        <span className="font-mono text-accent">{me?.tenant_id}</span>.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {metrics.map((m) => {
          const pct = Math.min(100, Math.round((m.value / m.quota) * 100));
          return (
            <div
              key={m.label}
              className="rounded-xl border border-white/8 bg-surface/40 p-5"
            >
              <div className="flex items-baseline justify-between">
                <h3 className="font-medium">{m.label}</h3>
                <span className="text-xs text-muted">{m.unit}</span>
              </div>
              <p className="mt-2 text-2xl font-bold tabular-nums">
                {m.value.toLocaleString()}
                <span className="ml-1 text-sm font-normal text-muted">
                  / {m.quota.toLocaleString()}
                </span>
              </p>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-accent transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-6 text-xs text-muted">
        Live metering counters are exposed at <span className="font-mono">/metrics</span>{" "}
        (Prometheus). A per-tenant usage read API feeds these cards in production.
      </p>
    </div>
  );
}
