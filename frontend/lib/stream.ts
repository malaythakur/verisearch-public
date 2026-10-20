// SSE streaming client for token-by-token answers (/v1/answer).

import { API_BASE, ApiError } from "./api";
import { getAuthHeaders } from "./auth";
import type { StreamEvent } from "./types";

/**
 * Stream an answer token-by-token using Server-Sent Events.
 * Yields `token`, `citation`, `done`, and `error` events as they arrive.
 */
export async function* streamAnswer(
  query: string,
  session_id?: string,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const auth = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/v1/answer`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...auth,
    },
    body: JSON.stringify({ query, stream: true, session_id: session_id ?? null }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new ApiError(`Stream failed (${res.status})`, "stream_failed", res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const ev = parseSSEFrame(frame);
      if (ev) yield ev;
    }
  }
}

function parseSSEFrame(frame: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;

  let payload: any;
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return null;
  }

  switch (event) {
    case "token":
      return { type: "token", text: payload.text ?? "", index: payload.index ?? 0 };
    case "citation":
      return { type: "citation", citation: payload };
    case "done":
      return { type: "done", answer: payload.answer ?? "", citations: payload.citations ?? [] };
    case "error":
      return { type: "error", code: payload.code ?? "error", message: payload.message ?? "" };
    default:
      return null;
  }
}
