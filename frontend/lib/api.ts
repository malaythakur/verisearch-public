// Typed API client for the Verisearch backend.
// All functions return either the typed payload or throw an ApiError.

import type {
  AnswerResponse,
  ErasureResult,
  IndexResponse,
  MeResponse,
  PipelineResponse,
  PipelineStepInput,
  ResearchEventsResponse,
  ResearchReport,
  ResearchResponse,
  ResidencyReport,
  SearchParams,
  SearchResponse,
  SessionResponse,
} from "./types";
import { getAuthHeaders } from "./auth";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "https://verisearch-production.up.railway.app";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const auth = await getAuthHeaders();
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...auth,
        ...(init?.headers ?? {}),
      },
    });
  } catch (e) {
    throw new ApiError(
      "Network error — could not reach the API.",
      "network_error",
      0
    );
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(
      err?.message ?? `Request failed (${res.status})`,
      err?.code ?? "request_failed",
      res.status
    );
  }

  // Backend may return a 200 with an embedded error (e.g. /v1/answer)
  const embedded = (data as { error?: { code?: string; message?: string } })?.error;
  if (embedded?.code) {
    throw new ApiError(embedded.message ?? "Error", embedded.code, res.status);
  }

  return data as T;
}

export function indexDocument(url: string, content: string): Promise<IndexResponse> {
  return request<IndexResponse>("/v1/index", {
    method: "POST",
    body: JSON.stringify({ url, content }),
  });
}

/** Upload a file (PDF/DOCX/TXT/MD/HTML); the server extracts text and indexes it. */
export async function uploadDocument(file: File): Promise<IndexResponse> {
  const form = new FormData();
  form.append("file", file);
  // NOTE: do not set Content-Type — the browser sets the multipart boundary.
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/v1/upload`, {
    method: "POST",
    headers: { ...auth },
    body: form,
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(
      err?.message ?? `Upload failed (${res.status})`,
      err?.code ?? "upload_failed",
      res.status
    );
  }
  return data as IndexResponse;
}

export function search(params: SearchParams | string): Promise<SearchResponse> {
  const body =
    typeof params === "string" ? { query: params, mode: "hybrid" } : params;
  return request<SearchResponse>("/v1/search", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function findSimilar(
  url: string,
  num_results = 10
): Promise<SearchResponse> {
  return request<SearchResponse>("/v1/find_similar", {
    method: "POST",
    body: JSON.stringify({ url, num_results }),
  });
}

export function answer(
  query: string,
  session_id?: string
): Promise<AnswerResponse> {
  return request<AnswerResponse>("/v1/answer", {
    method: "POST",
    body: JSON.stringify({ query, stream: false, session_id: session_id ?? null }),
  });
}

export function createSession(retention_days = 14): Promise<SessionResponse> {
  return request<SessionResponse>("/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ retention_days }),
  });
}

export function deleteSession(session_id: string): Promise<void> {
  return request<void>(`/v1/sessions/${encodeURIComponent(session_id)}`, {
    method: "DELETE",
  });
}

export function createResearch(
  research_goal: string,
  opts?: { session_id?: string; max_steps?: number }
): Promise<ResearchResponse> {
  return request<ResearchResponse>("/v1/research", {
    method: "POST",
    body: JSON.stringify({
      research_goal,
      session_id: opts?.session_id ?? null,
      max_steps: opts?.max_steps ?? null,
    }),
  });
}

export function getResearch(job_id: string): Promise<ResearchReport> {
  return request<ResearchReport>(`/v1/research/${encodeURIComponent(job_id)}`);
}

export function getResearchEvents(
  job_id: string,
  lastEventId?: number
): Promise<ResearchEventsResponse> {
  return request<ResearchEventsResponse>(
    `/v1/research/${encodeURIComponent(job_id)}/events`,
    lastEventId != null
      ? { headers: { "Last-Event-ID": String(lastEventId) } }
      : undefined
  );
}

export function createPipeline(
  name: string,
  steps: PipelineStepInput[]
): Promise<PipelineResponse> {
  return request<PipelineResponse>("/v1/pipelines", {
    method: "POST",
    body: JSON.stringify({ name, steps }),
  });
}


// --- Enterprise / Phase 13 ---

export function getMe(): Promise<MeResponse> {
  return request<MeResponse>("/v1/me");
}

export function getResidency(): Promise<ResidencyReport> {
  return request<ResidencyReport>("/v1/tenant/residency");
}

export function eraseTenant(): Promise<ErasureResult> {
  return request<ErasureResult>("/v1/tenant/erasure", { method: "POST" });
}

/** Fetch the tenant's audit log export (NDJSON) as parsed line objects. */
export async function exportAudit(): Promise<Record<string, unknown>[]> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/v1/audit/export`, {
    headers: { ...auth },
  });
  if (!res.ok) {
    throw new ApiError(`Audit export failed (${res.status})`, "audit_export_failed", res.status);
  }
  const text = await res.text();
  return text
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      try {
        return JSON.parse(line) as Record<string, unknown>;
      } catch {
        return { raw: line };
      }
    });
}


// --- Document management (Phase 13 follow-up) ---

export interface DocumentSummary {
  document_id: string;
  source_url: string;
  title: string;
  version: number;
}

export function listDocuments(): Promise<{ documents: DocumentSummary[]; total: number }> {
  return request<{ documents: DocumentSummary[]; total: number }>("/v1/documents");
}

export function deleteDocument(documentId: string): Promise<void> {
  return request<void>(`/v1/documents/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
  });
}


// --- Live web retrieval (open-web fetch via the compliance-checked crawler) ---

export interface WebFetchResult {
  url: string;
  canonical_url: string;
  http_status: number;
  content_type: string;
  characters: number;
  indexed: boolean;
  document_id: string | null;
  version: number | null;
  text?: string;
}

/** Fetch a live web URL (robots/throttle/opt-out respected). Optionally index it. */
export function fetchWeb(
  url: string,
  opts?: { index?: boolean; include_text?: boolean }
): Promise<WebFetchResult> {
  return request<WebFetchResult>("/v1/web/fetch", {
    method: "POST",
    body: JSON.stringify({
      url,
      index: opts?.index ?? false,
      include_text: opts?.include_text ?? true,
    }),
  });
}
