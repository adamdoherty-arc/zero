# Plan: Council Review, Re-grade, and Parliamentary UI Overhaul

## Context

The Digital Twin Council (Next.js 15 / React 19 / Gemini 3.1) already wires the three features the user described — prebuilt department templates ([council-templates.ts](src/lib/templates/council-templates.ts) ships 6 org templates: Engineering, Product & Design, Sales, Customer Success, Leadership, Revenue Ops, Cross-Functional), prompt-driven team assembly ([api/assemble](src/app/api/assemble/) + 6 project templates), council Q&A with streaming ([api/execute/[sessionId]](src/app/api/execute/) over SSE), per-twin drill-down ([ResultsMemberExpandable.tsx](src/components/results/ResultsMemberExpandable.tsx)), and consensus synthesis ([synthesizer.ts](src/lib/orchestration/synthesizer.ts) — weighted vote × confidence, low-consensus escalation under 50). What's missing is *evidence the loop holds end-to-end*, a graded baseline, distinctive (non-standard) visual identity, and a project update.

The user has four project-specific skills built for exactly this job: `grade-project` (10-dim spec scorecard), `dtc-audit` (15-dim full-stack with `docs/AUDIT_HISTORY.md` trend tracking), `dtc-iterate` (audit→fix→re-grade), `dtc-ui` (iterative DESIGN.md-driven overhaul with `docs/DESIGN_HISTORY.md`). Decisions taken: **Parliamentary chamber aesthetic**, **full pipeline** (audit → research → UI overhaul → tech fixes → re-grade).

## Approach

Six sequential phases. Each phase has a clear artifact so the project update at the end can cite real numbers.

### Phase 1 — Verify the three features actually work

Read-only walkthrough confirming the user's described flow is unbroken before any changes. No fixes here; only flag gaps for Phase 5.

- Trace **prebuilt templates**: [council-templates.ts](src/lib/templates/council-templates.ts) → [TwinSelector.tsx](src/components/council/TwinSelector.tsx) → [council/[sessionId]/page.tsx](src/app/council/[sessionId]/page.tsx). Confirm regex filters cover the org and each template has a maxSize ceiling.
- Trace **prompt → team assembly**: [AssembleInput.tsx](src/components/question/AssembleInput.tsx) → POST [/api/assemble](src/app/api/assemble/route.ts) → `assembleByTopic()` in [digital-twin-client.ts](src/lib/api/digital-twin-client.ts). Confirm document search hits JIRA/Slack/Confluence/Gmail and maps participants to twins.
- Trace **ask question → fan-out → drill-down → consensus**: [QuestionInput.tsx](src/components/question/QuestionInput.tsx) → POST [/api/execute/[sessionId]](src/app/api/execute/[sessionId]/route.ts) → SSE consumer [useExecutionStream.ts](src/hooks/useExecutionStream.ts) → [TwinResponseCard.tsx](src/components/execution/TwinResponseCard.tsx) → results page → [synthesizer.ts](src/lib/orchestration/synthesizer.ts) (weighted vote, alternatives, escalation under 50% consensus).
- Smoke test in browser if `GEMINI_API_KEY` and twins are configured: `npm run dev`, run one query through each entry point (template council + prompt-assembled council), confirm streaming, drill-down, consensus all render.
- Output: short feature-readiness checklist (works / partial / broken) included in the final project update.

### Phase 2 — Baseline grading

Run both grading skills in parallel — they cover orthogonal axes:

- `/grade-project` → scores against the spec ([digital-twin-council-idea.md](.claude/skills/grade-project/digital-twin-council-idea.md)) on the 10-dim rubric: Data Model, API Integration, Council Recommendation, Streaming, Schema, Vote/Synthesis, Results UI, Polish, History, Mock Mode.
- `/dtc-audit` → 15-dim full-stack: Build, TypeScript, API, Security, Errors, Streaming, LLM Quality, UI/UX, Data, State, Code Quality, Mock Mode, Accessibility, Docs, Deployment. Initializes `docs/AUDIT_HISTORY.md` for delta tracking.

Capture both composite scores and per-dimension breakdowns. These are the "before" numbers for the project update.

### Phase 3 — External research

Use `WebSearch` (April 2026) for three targeted queries — not exhaustive, just enough to validate or challenge the current consensus mechanism and UI direction:

1. Multi-agent council/jury patterns and consensus mechanisms in LLM ensembles (weighted voting, confidence calibration, escalation thresholds).
2. Best practices for multi-agent UIs that show parallel streaming responses with drill-down (e.g. Anthropic's parallel-tool-use patterns, Manus-style multi-agent dashboards).
3. Parliamentary / legislative / chamber-themed product design references (typography, color systems, vote visualization).

Output: a brief "research notes" section to fold into the DESIGN.md update and the synthesizer review. If the research surfaces a flaw in the current weighted-vote logic (e.g. confidence-as-weight is known-biased), flag for Phase 5.

### Phase 4 — UI overhaul: Parliamentary chamber

Drive via `/dtc-ui`. Constraint: this skill applies ONE focused improvement per run, but for a full aesthetic shift we'll seed it with a Parliamentary chamber DESIGN.md and let it sequence the highest-impact passes.

Aesthetic spec (seed for DESIGN.md):

- **Typography**: Cormorant Garamond (or Playfair Display) for headlines and twin names; Inter or Source Sans for body. Small caps for section labels (THE COUNCIL · CONSENSUS · MOTION).
- **Palette**: Ivory paper `#FAF6EE` background, brass accent `#B08D57`, marble divider `#D8D2C5`, ink `#1A1814` text, muted oxblood `#7A1F2A` for dissent. Optional dark mode = "chamber at night" (deep navy + brass).
- **Layout**: Council page renders as a semicircle/arc of seats (CSS grid + transforms) instead of a flat list. Results page treats the synthesis as a "MOTION" with AYE / NAY / ABSTAIN tally bars. Live execution shows seats lighting up as twins respond.
- **Micro-detail**: serif numerals for confidence/consensus scores; subtle marble texture (SVG noise) on dividers; vote tally bars use brass on ivory. No emoji icons in the UI; replace with monoline SVG symbols.
- **What stays**: Tailwind utility classes, Radix primitives, Framer Motion. We're restyling tokens and a handful of components, not rewriting the stack.

Order of `dtc-ui` passes (each is one run, persisted to `docs/DESIGN_HISTORY.md`):

1. **Tokens & typography** — globals.css design tokens, Tailwind theme extension, Google Fonts wiring (Cormorant + Inter).
2. **Council layout** — semicircle seat arrangement on [council/[sessionId]/page.tsx](src/app/council/[sessionId]/page.tsx) and [TwinCard.tsx](src/components/council/TwinCard.tsx).
3. **Results "MOTION" view** — [PrimaryRecommendation.tsx](src/components/results/PrimaryRecommendation.tsx) + [VoteVisualization.tsx](src/components/results/VoteVisualization.tsx) get the AYE/NAY tally treatment.
4. **Execution chamber** — [TwinResponseCard.tsx](src/components/execution/TwinResponseCard.tsx) renders as illuminating seats during streaming.
5. **Header / step indicator** — [Header.tsx](src/components/layout/Header.tsx) + [StepIndicator.tsx](src/components/layout/StepIndicator.tsx) gain the chamber/serif treatment.

If `dtc-ui` finishes only some passes within the run window, that's fine — it persists state and the remaining passes are queued for next time.

### Phase 5 — Technical fixes via `/dtc-iterate`

One sprint pass focused on whatever the Phase 2 audit ranked highest impact ÷ effort. Likely candidates from the structural map:

- No test suite (`vitest` or `jest` setup, integration test for execute SSE flow).
- No `typecheck` script in package.json (add `tsc --noEmit`).
- No CI/CD workflow visible (`.github/workflows/ci.yml` for build + lint + typecheck).
- Synthesizer biases / consensus thresholds flagged by Phase 3 research.
- `mockTwins` leaking into the production lookup path in [synthesizer.ts:11](src/lib/orchestration/synthesizer.ts#L11) — guard behind `USE_MOCK`.

`dtc-iterate` picks the focus area itself; we don't dictate. The skill commits each fix atomically and re-runs the audit so the delta is visible.

### Phase 6 — Re-grade and project update

- Re-run `/grade-project` and `/dtc-audit`. Both will read `docs/AUDIT_HISTORY.md` and emit a delta vs. baseline.
- Write a project update (single message to user, not a file) with:
  - Feature readiness checklist from Phase 1
  - Baseline composite scores (Phase 2)
  - Top research findings worth acting on (Phase 3)
  - UI passes completed + screenshots if `browse` skill is available (Phase 4)
  - Tech fixes shipped + commit list (Phase 5)
  - Final composite scores + delta vs. baseline (Phase 6)
  - Top 3 highest-leverage next moves (per-dimension recommendations from re-grade)

## Critical files

**Read-only verification**:
- [src/lib/templates/council-templates.ts](src/lib/templates/council-templates.ts)
- [src/app/api/assemble/route.ts](src/app/api/assemble/route.ts)
- [src/app/api/execute/[sessionId]/route.ts](src/app/api/execute/[sessionId]/route.ts)
- [src/lib/orchestration/synthesizer.ts](src/lib/orchestration/synthesizer.ts)
- [src/lib/orchestration/council-recommender.ts](src/lib/orchestration/council-recommender.ts)
- [src/hooks/useExecutionStream.ts](src/hooks/useExecutionStream.ts)

**UI surfaces touched in Phase 4**:
- [src/app/globals.css](src/app/globals.css), [tailwind.config.ts](tailwind.config.ts) (or v4 inline equivalent)
- [src/app/council/[sessionId]/page.tsx](src/app/council/[sessionId]/page.tsx)
- [src/app/results/[sessionId]/page.tsx](src/app/results/[sessionId]/page.tsx)
- [src/components/council/TwinCard.tsx](src/components/council/TwinCard.tsx), [TwinSelector.tsx](src/components/council/TwinSelector.tsx)
- [src/components/results/PrimaryRecommendation.tsx](src/components/results/PrimaryRecommendation.tsx), [VoteVisualization.tsx](src/components/results/VoteVisualization.tsx), [ResultsMemberExpandable.tsx](src/components/results/ResultsMemberExpandable.tsx)
- [src/components/execution/TwinResponseCard.tsx](src/components/execution/TwinResponseCard.tsx)
- [src/components/layout/Header.tsx](src/components/layout/Header.tsx), [StepIndicator.tsx](src/components/layout/StepIndicator.tsx)

**Skill artifacts produced/updated**:
- `docs/AUDIT_HISTORY.md` (created by `dtc-audit` on first run, appended thereafter)
- `docs/DESIGN_HISTORY.md` (created by `dtc-ui` on first run)
- `DESIGN.md` (Parliamentary chamber spec — created or replaced)

## Reuse of existing utilities

- `cn()` in [src/lib/utils/cn.ts](src/lib/utils/cn.ts) for the new component variants — don't introduce a second classname helper.
- Existing Radix primitives (Accordion, Dialog, Tooltip) carry into the new aesthetic; we restyle, not replace.
- `computeWeightedVote()` and `buildSuggestedExperts()` in [synthesizer.ts](src/lib/orchestration/synthesizer.ts) — keep the math, only change presentation in Phase 4 and only adjust thresholds in Phase 5 if research justifies it.
- `useExecutionStream` hook stays as-is; chamber UI in Phase 4 reads from the same events.

## Verification

End-to-end checks the project must still pass after Phase 4 + 5:

1. `npm run build` — clean.
2. `npm run lint` — no new errors.
3. `npm run dev` + browser walkthrough (use `browse` skill if available; otherwise manual): home → assemble by department template → ask a question → drill into one twin → see consensus + AYE/NAY tally. Repeat with prompt-assembled team. Both flows must reach a synthesis screen without console errors.
4. Re-run `/dtc-audit`. Expect: composite score increases vs. baseline; UI/UX dimension shows the largest gain; no dimension regresses by more than 5 points.
5. Re-run `/grade-project`. Expect: composite score increases; no rubric dimension drops.
6. `git log --oneline` since plan start — every change is a discrete commit, no rolled-up "WIP" commits.

If any verification step fails, the project update calls it out explicitly rather than glossing over it.
