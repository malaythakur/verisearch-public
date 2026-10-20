# Verisearch Frontend

Next.js 14 (App Router) + TypeScript + Tailwind CSS + Framer Motion + GSAP.

Implements the full UI for [Verisearch](https://github.com/malaythakur/verisearch):
search, cited answers (with SSE streaming), document indexing, multi-hop
research dashboard, and a drag-and-drop pipeline builder.

## Quick start

```bash
cd frontend
npm install
cp .env.local.example .env.local   # points at the live API by default
npm run dev
```

Open http://localhost:3000

## Environment

| Var | Default | Description |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://verisearch-production.up.railway.app` | Backend API base URL |

## Pages

| Route | Feature |
| --- | --- |
| `/` | Landing — GSAP hero + scroll-triggered architecture visualization |
| `/search` | Hybrid/neural/keyword search with animated result cards |
| `/answer` | Streaming (SSE) AI answers with span-level citation highlighting |
| `/index-doc` | Index a document (URL + content) |
| `/research` | Launch multi-hop research, live event timeline + report |
| `/pipelines` | Drag-and-drop pipeline builder with flow preview |

## Architecture notes

- `lib/api.ts` — typed API client (incl. `streamAnswer` async generator for SSE)
- `lib/types.ts` — request/response types matching the backend `/v1/*` contract
- `lib/useReducedMotion.ts` — `prefers-reduced-motion` + debounce hooks
- All animations use GPU-accelerated transforms and respect reduced-motion.

## Brand

- Background `#0f0f1a`, surface `#16162a`, accent `#00d4ff`
- Font: Inter
