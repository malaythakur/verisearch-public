# Frontend Contribution Issues

Build the frontend for Verisearch. Issues are ordered from beginner to advanced.
Stack: **Next.js 14 (App Router) + TypeScript + Tailwind CSS + Framer Motion + GSAP**

Copy each block below into a new GitHub issue at:
https://github.com/malaythakur/verisearch/issues/new

---

## 🟢 BEGINNER

### Issue 1: Project setup — Next.js + Tailwind + Motion libraries
**Labels:** `good first issue`, `frontend`, `setup`

**Description:**
Set up the frontend foundation in a new `/frontend` directory.

**Tasks:**
- [ ] Initialize Next.js 14 with App Router and TypeScript
- [ ] Install and configure Tailwind CSS
- [ ] Install `framer-motion` and `gsap`
- [ ] Set up a clean folder structure (`/components`, `/lib`, `/app`)
- [ ] Add a `.env.local.example` with `NEXT_PUBLIC_API_URL=https://verisearch-production.up.railway.app`
- [ ] Create a basic layout with dark theme (match brand: bg #0f0f1a, accent #00d4ff)

**Acceptance:** `npm run dev` shows a styled landing page with the Verisearch name.

---

### Issue 2: API client wrapper
**Labels:** `good first issue`, `frontend`

**Description:**
Create a typed API client to call the Verisearch backend.

**Tasks:**
- [ ] Create `/lib/api.ts` with functions: `indexDocument()`, `search()`, `answer()`, `createSession()`, `createResearch()`
- [ ] Use the base URL from env var
- [ ] Add TypeScript types for all request/response shapes
- [ ] Handle errors gracefully (return typed error objects)

**Acceptance:** A test page can call `search("test")` and log results.

---

### Issue 3: Landing / hero section with GSAP entrance animation
**Labels:** `good first issue`, `frontend`, `animation`

**Description:**
Build the hero section with a smooth entrance animation.

**Tasks:**
- [ ] Hero headline: "AI Search with Verifiable Citations"
- [ ] Animated subtext and CTA button
- [ ] Use GSAP timeline for staggered text reveal on load
- [ ] Add a subtle gradient glow behind the headline
- [ ] Responsive on mobile

**Acceptance:** Headline animates in on page load, looks polished.

---

## 🟡 INTERMEDIATE

### Issue 4: Search interface with live results
**Labels:** `frontend`, `feature`

**Description:**
Build the core search experience.

**Tasks:**
- [ ] Search bar with mode toggle (neural / keyword / hybrid)
- [ ] Call `/v1/search` and display ranked results as cards
- [ ] Each card shows: title, URL, score (as a progress bar), credibility badge
- [ ] Framer Motion stagger animation on results appearing
- [ ] Loading skeleton while fetching
- [ ] Empty state when no results

**Acceptance:** User types a query, sees animated result cards with scores.

---

### Issue 5: Document indexing UI
**Labels:** `frontend`, `feature`

**Description:**
Let users add documents to search.

**Tasks:**
- [ ] Form with URL field + content textarea (or file upload)
- [ ] Call `/v1/index` on submit
- [ ] Show success toast with the returned `document_id`
- [ ] Validation: both fields required
- [ ] Smooth Framer Motion modal/drawer for the form

**Acceptance:** User indexes a document and sees confirmation.

---

### Issue 6: Answer view with citation highlighting
**Labels:** `frontend`, `feature`, `animation`

**Description:**
The flagship feature — show AI answers with clickable citations.

**Tasks:**
- [ ] Call `/v1/answer` with a question
- [ ] Display the answer text
- [ ] Highlight cited spans (use `answer_start`/`answer_end` offsets)
- [ ] On citation hover/click, show the source document and highlight `source_start`/`source_end`
- [ ] Animate citations appearing with Framer Motion
- [ ] Side-by-side: answer on left, source on right

**Acceptance:** User asks a question, sees answer with highlighted, clickable citations linking to source text.

---

### Issue 7: SSE streaming for token-by-token answers
**Labels:** `frontend`, `feature`, `streaming`

**Description:**
Stream answers in real-time instead of waiting for the full response.

**Tasks:**
- [ ] Connect to `/v1/answer` with `Accept: text/event-stream`
- [ ] Parse SSE events: `token`, `citation`, `done`, `error`
- [ ] Render tokens as they arrive (typewriter effect)
- [ ] Append citations live as they stream
- [ ] Handle errors and stream close

**Acceptance:** Answer appears token-by-token like ChatGPT, citations pop in live.

---

## 🔴 ADVANCED

### Issue 8: Research dashboard with live event stream
**Labels:** `frontend`, `feature`, `advanced`

**Description:**
Visualize multi-hop research jobs in real-time.

**Tasks:**
- [ ] Form to launch research (`/v1/research`)
- [ ] Poll/stream `/v1/research/{job_id}/events`
- [ ] Visualize the research plan as an animated step-by-step timeline (GSAP)
- [ ] Show each step status: queued → running → completed
- [ ] Display citations as they're gathered
- [ ] Render the final report with formatting
- [ ] Animate plan steps lighting up as they execute

**Acceptance:** User launches research, watches the plan execute step-by-step with smooth animations, sees the final cited report.

---

### Issue 9: Pipeline builder (drag-and-drop)
**Labels:** `frontend`, `feature`, `advanced`

**Description:**
Visual builder for programmable retrieval pipelines.

**Tasks:**
- [ ] Drag-and-drop interface to compose pipeline steps (filter / reranker / transform)
- [ ] Each step is a draggable card with config options
- [ ] Reorder steps with smooth Framer Motion drag animations
- [ ] Call `/v1/pipelines` to save
- [ ] Validate step count (1-20) and show errors
- [ ] Preview pipeline as a flow diagram

**Acceptance:** User drags steps to build a pipeline, reorders them smoothly, saves it.

---

### Issue 10: Animated architecture visualization
**Labels:** `frontend`, `feature`, `advanced`, `animation`

**Description:**
An interactive landing-page section showing the system architecture.

**Tasks:**
- [ ] Concentric circles: Ingest (core) → Query (middle) → Edge (outer)
- [ ] GSAP scroll-triggered animation as user scrolls
- [ ] Hover on each layer reveals its components
- [ ] Animated data-flow particles moving between layers
- [ ] Responsive and performant

**Acceptance:** Scrolling reveals the architecture with smooth, performant animations.

---

### Issue 11: Performance — animation optimization
**Labels:** `frontend`, `performance`, `advanced`

**Description:**
Ensure all animations run at 60fps.

**Tasks:**
- [ ] Use `will-change` and GPU-accelerated transforms only
- [ ] Lazy-load GSAP plugins
- [ ] Add `prefers-reduced-motion` support for accessibility
- [ ] Debounce search input
- [ ] Lighthouse score 90+ on performance

**Acceptance:** Lighthouse performance ≥ 90, animations smooth on mid-range devices.

---

## Getting Started for Contributors

1. Fork the repo
2. Pick an issue (start with 🟢 if new)
3. Comment "I'm working on this"
4. Create a branch: `git checkout -b frontend/issue-N-short-name`
5. The backend API is live at: https://verisearch-production.up.railway.app
6. API docs: https://verisearch-production.up.railway.app/docs
7. Submit a PR — reviewed same day

**Brand guidelines:**
- Background: `#0f0f1a`
- Accent: `#00d4ff`
- Font: Inter or system-ui
- Dark theme first
