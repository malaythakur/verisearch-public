"use client";

import { useCallback, useEffect, useState } from "react";
import { listDocuments, type DocumentSummary } from "@/lib/api";

// Lightweight hook to know whether the signed-in user has any documents in
// their private corpus. Used to drive onboarding guidance (search/answer/
// research are only useful once the corpus has content).
export function useCorpus() {
  const [docs, setDocs] = useState<DocumentSummary[] | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listDocuments();
      setDocs(res.documents);
    } catch {
      // best-effort; treat as unknown (null)
      setDocs(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const count = docs?.length ?? 0;
  return { docs, count, isEmpty: docs !== null && count === 0, loading, refresh };
}
