// Type definitions matching the Verisearch backend API (/v1/*).

export type SearchMode = "neural" | "keyword" | "hybrid";

export interface Provenance {
  credibility_score: number;
  ai_generated_likelihood: number;
}

export interface SearchResult {
  document_id: string;
  url: string;
  title: string | null;
  score: number;
  published_at?: string | null;
  provenance: Provenance;
  version: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

export interface SearchParams {
  query: string;
  mode?: SearchMode;
  num_results?: number;
  filters?: string | null;
  pipeline_id?: string | null;
  min_credibility?: number | null;
  max_ai_generated_likelihood?: number | null;
}

export interface IndexResponse {
  document_id?: string;
  version?: number;
  is_new?: boolean;
  message_id?: string;
  status?: string;
  filename?: string;
  source_url?: string;
  characters?: number;
}

export interface Citation {
  document_id: string;
  version: number;
  answer_start: number;
  answer_end: number;
  source_start?: number;
  source_end?: number;
}

export interface AnswerResponse {
  answer: string;
  citations: Citation[];
  error?: ApiErrorBody;
}

export interface SessionResponse {
  session_id: string;
  tenant_id: string;
  retention_days: number;
  expires_at: string;
}

export interface ResearchResponse {
  job_id: string;
}

export interface ResearchReport {
  job_id: string;
  text: string;
  structured_payload: Record<string, unknown> | null;
  citations: Citation[];
  is_partial: boolean;
}

export interface ResearchEvent {
  event_id: number;
  type: string;
  payload: Record<string, unknown>;
  emitted_at: string;
}

export interface ResearchEventsResponse {
  events: ResearchEvent[];
}

export interface PipelineStepInput {
  name: string;
  config?: Record<string, unknown>;
  timeout_ms?: number;
}

export interface PipelineResponse {
  pipeline_id: string;
  name: string;
  steps: { name: string; type: string; timeout_ms: number }[];
  created_at: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
}

// Streaming SSE event shapes for /v1/answer
export type StreamEvent =
  | { type: "token"; text: string; index: number }
  | { type: "citation"; citation: Citation }
  | { type: "done"; answer: string; citations: Citation[] }
  | { type: "error"; code: string; message: string };


// --- Enterprise / Phase 13 ---

export interface MeResponse {
  tenant_id: string;
  subject: string;
  auth_kind: "human" | "machine";
  roles: string[];
  permissions: string[];
  deployment_mode: string;
  data_residency_region: string;
}

export interface ResidencyReport {
  deployment_mode: string;
  data_residency_region: string;
  stores: Record<string, string>;
  note: string;
}

export interface ErasureResult {
  tenant_id: string;
  status: string;
  records_deleted: number;
  audit_preserved: boolean;
  categories: Record<string, number>;
}
