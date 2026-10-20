# Creates 11 frontend collaboration issues on github.com/malaythakur/verisearch
# Usage: gh auth login   (one time)
#        .\scripts\create_frontend_issues.ps1

$ErrorActionPreference = "Stop"
$repo = "malaythakur/verisearch"

# Resolve gh.exe — handle the case where the install added it to PATH
# but the current shell session was started before that happened.
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) {
    $candidates = @(
        "C:\Program Files\GitHub CLI\gh.exe",
        "C:\Program Files (x86)\GitHub CLI\gh.exe",
        "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe"
    )
    $gh = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $gh) {
    Write-Error "gh.exe not found. Install via 'winget install GitHub.cli' and restart this shell."
    exit 1
}
Write-Host "Using gh: $gh" -ForegroundColor DarkGray

# Verify auth
& $gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "gh is not authenticated. Run: & '$gh' auth login"
    exit 1
}

# Ensure all required labels exist (idempotent — ignore if already present)
$labels = @(
    @{ name = "good first issue"; color = "7057ff"; desc = "Good for newcomers" },
    @{ name = "frontend";         color = "00d4ff"; desc = "Frontend / UI work" },
    @{ name = "setup";            color = "c2e0c6"; desc = "Project setup / scaffolding" },
    @{ name = "feature";          color = "0e8a16"; desc = "New feature" },
    @{ name = "animation";        color = "f9d0c4"; desc = "Motion / GSAP / Framer Motion" },
    @{ name = "streaming";        color = "fbca04"; desc = "Real-time / SSE / streaming" },
    @{ name = "advanced";         color = "b60205"; desc = "Advanced level task" },
    @{ name = "performance";      color = "5319e7"; desc = "Performance / optimization" }
)

foreach ($l in $labels) {
    & $gh label create $l.name --repo $repo --color $l.color --description $l.desc 2>$null | Out-Null
}

# Issue payloads
$issues = @(
    @{
        title  = "[Frontend] Project setup — Next.js + Tailwind + Motion libraries"
        labels = "good first issue,frontend,setup"
        body   = @'
**Difficulty:** 🟢 Beginner

Set up the frontend foundation in a new `/frontend` directory.

### Tasks
- [ ] Initialize Next.js 14 with App Router and TypeScript
- [ ] Install and configure Tailwind CSS
- [ ] Install `framer-motion` and `gsap`
- [ ] Set up a clean folder structure (`/components`, `/lib`, `/app`)
- [ ] Add a `.env.local.example` with `NEXT_PUBLIC_API_URL=https://verisearch-production.up.railway.app`
- [ ] Create a basic layout with dark theme (bg `#0f0f1a`, accent `#00d4ff`)

### Acceptance
`npm run dev` shows a styled landing page with the Verisearch name.
'@
    },
    @{
        title  = "[Frontend] Typed API client wrapper"
        labels = "good first issue,frontend"
        body   = @'
**Difficulty:** 🟢 Beginner

Create a typed API client to call the Verisearch backend.

### Tasks
- [ ] Create `/lib/api.ts` with: `indexDocument()`, `search()`, `answer()`, `createSession()`, `createResearch()`
- [ ] Use the base URL from env var
- [ ] Add TypeScript types for all request/response shapes
- [ ] Handle errors gracefully (return typed error objects)

### Acceptance
A test page can call `search("test")` and log results.

API docs: https://verisearch-production.up.railway.app/docs
'@
    },
    @{
        title  = "[Frontend] Landing / hero section with GSAP entrance animation"
        labels = "good first issue,frontend,animation"
        body   = @'
**Difficulty:** 🟢 Beginner

Build the hero section with a smooth entrance animation.

### Tasks
- [ ] Hero headline: "AI Search with Verifiable Citations"
- [ ] Animated subtext and CTA button
- [ ] Use GSAP timeline for staggered text reveal on load
- [ ] Add a subtle gradient glow behind the headline
- [ ] Responsive on mobile

### Acceptance
Headline animates in on page load, looks polished.
'@
    },
    @{
        title  = "[Frontend] Search interface with live results"
        labels = "frontend,feature"
        body   = @'
**Difficulty:** 🟡 Intermediate

Build the core search experience.

### Tasks
- [ ] Search bar with mode toggle (neural / keyword / hybrid)
- [ ] Call `/v1/search` and display ranked results as cards
- [ ] Each card shows: title, URL, score (as a progress bar), credibility badge
- [ ] Framer Motion stagger animation on results appearing
- [ ] Loading skeleton while fetching
- [ ] Empty state when no results

### Acceptance
User types a query, sees animated result cards with scores.
'@
    },
    @{
        title  = "[Frontend] Document indexing UI"
        labels = "frontend,feature"
        body   = @'
**Difficulty:** 🟡 Intermediate

Let users add documents to search.

### Tasks
- [ ] Form with URL field + content textarea (or file upload)
- [ ] Call `/v1/index` on submit
- [ ] Show success toast with the returned `document_id`
- [ ] Validation: both fields required
- [ ] Smooth Framer Motion modal/drawer for the form

### Acceptance
User indexes a document and sees confirmation.
'@
    },
    @{
        title  = "[Frontend] Answer view with citation highlighting"
        labels = "frontend,feature,animation"
        body   = @'
**Difficulty:** 🟡 Intermediate

The flagship feature — show AI answers with clickable citations.

### Tasks
- [ ] Call `/v1/answer` with a question
- [ ] Display the answer text
- [ ] Highlight cited spans (use `answer_start`/`answer_end` offsets)
- [ ] On citation hover/click, show the source document and highlight `source_start`/`source_end`
- [ ] Animate citations appearing with Framer Motion
- [ ] Side-by-side: answer on left, source on right

### Acceptance
User asks a question, sees answer with highlighted, clickable citations linking to source text.
'@
    },
    @{
        title  = "[Frontend] SSE streaming for token-by-token answers"
        labels = "frontend,feature,streaming"
        body   = @'
**Difficulty:** 🟡 Intermediate

Stream answers in real-time instead of waiting for the full response.

### Tasks
- [ ] Connect to `/v1/answer` with `Accept: text/event-stream`
- [ ] Parse SSE events: `token`, `citation`, `done`, `error`
- [ ] Render tokens as they arrive (typewriter effect)
- [ ] Append citations live as they stream
- [ ] Handle errors and stream close

### Acceptance
Answer appears token-by-token like ChatGPT, citations pop in live.
'@
    },
    @{
        title  = "[Frontend] Research dashboard with live event stream"
        labels = "frontend,feature,advanced"
        body   = @'
**Difficulty:** 🔴 Advanced

Visualize multi-hop research jobs in real-time.

### Tasks
- [ ] Form to launch research (`/v1/research`)
- [ ] Poll/stream `/v1/research/{job_id}/events`
- [ ] Visualize the research plan as an animated step-by-step timeline (GSAP)
- [ ] Show each step status: queued → running → completed
- [ ] Display citations as they're gathered
- [ ] Render the final report with formatting
- [ ] Animate plan steps lighting up as they execute

### Acceptance
User launches research, watches the plan execute step-by-step with smooth animations, sees the final cited report.
'@
    },
    @{
        title  = "[Frontend] Pipeline builder (drag-and-drop)"
        labels = "frontend,feature,advanced"
        body   = @'
**Difficulty:** 🔴 Advanced

Visual builder for programmable retrieval pipelines.

### Tasks
- [ ] Drag-and-drop interface to compose pipeline steps (filter / reranker / transform)
- [ ] Each step is a draggable card with config options
- [ ] Reorder steps with smooth Framer Motion drag animations
- [ ] Call `/v1/pipelines` to save
- [ ] Validate step count (1-20) and show errors
- [ ] Preview pipeline as a flow diagram

### Acceptance
User drags steps to build a pipeline, reorders them smoothly, saves it.
'@
    },
    @{
        title  = "[Frontend] Animated architecture visualization"
        labels = "frontend,feature,advanced,animation"
        body   = @'
**Difficulty:** 🔴 Advanced

An interactive landing-page section showing the system architecture.

### Tasks
- [ ] Concentric circles: Ingest (core) → Query (middle) → Edge (outer)
- [ ] GSAP scroll-triggered animation as user scrolls
- [ ] Hover on each layer reveals its components
- [ ] Animated data-flow particles moving between layers
- [ ] Responsive and performant

### Acceptance
Scrolling reveals the architecture with smooth, performant animations.
'@
    },
    @{
        title  = "[Frontend] Performance — animation optimization"
        labels = "frontend,performance,advanced"
        body   = @'
**Difficulty:** 🔴 Advanced

Ensure all animations run at 60fps.

### Tasks
- [ ] Use `will-change` and GPU-accelerated transforms only
- [ ] Lazy-load GSAP plugins
- [ ] Add `prefers-reduced-motion` support for accessibility
- [ ] Debounce search input
- [ ] Lighthouse score 90+ on performance

### Acceptance
Lighthouse performance ≥ 90, animations smooth on mid-range devices.
'@
    }
)

$created = @()
foreach ($issue in $issues) {
    Write-Host "Creating: $($issue.title)" -ForegroundColor Cyan
    $bodyFile = New-TemporaryFile
    Set-Content -Path $bodyFile -Value $issue.body -Encoding UTF8
    try {
        $url = & $gh issue create `
            --repo $repo `
            --title $issue.title `
            --label $issue.labels `
            --body-file $bodyFile.FullName
        Write-Host "  -> $url" -ForegroundColor Green
        $created += $url
    } finally {
        Remove-Item $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Created $($created.Count) issues:" -ForegroundColor Yellow
$created | ForEach-Object { Write-Host "  $_" }
