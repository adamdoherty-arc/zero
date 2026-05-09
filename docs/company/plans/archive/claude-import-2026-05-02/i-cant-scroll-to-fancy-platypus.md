# Fix "can't scroll to bottom" in LLM Call Detail modal + audit other modals

## Context

User reports they cannot scroll to the bottom of the **LLM Call Detail** modal (screenshot: modal shown from [LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx) with SOURCE, MODEL, Quality Review, System Prompt, Prompt, Response sections). Asked to verify the bug in that component *and* audit every other modal in the app for the same pattern.

## Root cause

In [LLMConsole.tsx:229-554](frontend/src/pages/LLMConsole.tsx#L229-L554) the `CallDetailDialog` uses:

```
DialogContent  max-h-[85vh] flex flex-col overflow-hidden
  DialogHeader (no flex-shrink-0)
  ScrollArea   flex-1 -mr-3 pr-3
    ...metadata grid...
    Quality Review panel — has inner <pre max-h-48 overflow-y-auto>   ← nested scroll
    System Prompt       — <pre max-h-60 overflow-y-auto>              ← nested scroll
    Prompt              — <pre max-h-60 overflow-y-auto>              ← nested scroll
    Response            — <pre max-h-80 overflow-y-auto>              ← nested scroll
```

The outer `ScrollArea` is wired correctly (`flex-1` inside a bounded `flex flex-col` ancestor). The real bug is **nested wheel capture**: when the user scrolls with the pointer hovering over one of the inner `<pre>` blocks, the wheel event is consumed by the inner scroller. If the pre content fits inside its `max-h-*` cap the inner block has no scroll to consume, so the event is "eaten" silently — the outer modal does not advance. Result: user feels stuck, can't reach the bottom.

Secondary issue: `DialogHeader` lacks `flex-shrink-0`, so under very tall content it can compete for space against the `flex-1` ScrollArea sibling.

## Audit of other modals (sampled — same pattern or not?)

| Modal | File | Scroll pattern | Verdict |
|---|---|---|---|
| **LLM Call Detail** | [LLMConsole.tsx:276](frontend/src/pages/LLMConsole.tsx#L276) | outer `ScrollArea flex-1` + 4 inner `<pre>` each with own `overflow-y-auto` | **BUG — fix** |
| Sprint Detail | [components/sprint/SprintDetailDialog.tsx](frontend/src/components/sprint/SprintDetailDialog.tsx) | `h-[85vh] flex flex-col` + inner `flex-1 min-h-0 overflow-y-auto`, header is `flex-shrink-0` | correct |
| Ask AI | [components/AskAIDialog.tsx](frontend/src/components/AskAIDialog.tsx) | outer `max-h-[80vh] flex flex-col` + one ScrollArea region, input pinned with `mt-auto` | correct |
| Create Project | [components/CreateProjectDialog.tsx:145](frontend/src/components/CreateProjectDialog.tsx#L145) | `max-h-[85vh] overflow-y-auto` directly on DialogContent (single outer scroll) | works (content is short); **no change** |
| Browse Folder | [components/BrowseFolderDialog.tsx](frontend/src/components/BrowseFolderDialog.tsx) | `max-h-[70vh] flex flex-col` + inner `flex-1 overflow-y-auto` | correct |
| Ideas detail | [pages/Ideas.tsx](frontend/src/pages/Ideas.tsx) | `max-h-[80vh] flex flex-col overflow-hidden` | correct |

Only `CallDetailDialog` has the nested-scroll anti-pattern. Not system-wide — single site, single fix.

## Changes

Edit only [frontend/src/pages/LLMConsole.tsx](frontend/src/pages/LLMConsole.tsx):

1. **Line 277** — add `flex-shrink-0` to the DialogHeader so the header can never steal space from the scroll region:
   ```
   <DialogHeader className="flex-shrink-0">
   ```

2. **Line 447** (suggested-improvement `<pre>`) — remove `max-h-48 overflow-y-auto`:
   ```
   className="mt-2 p-2 rounded bg-slate-900/60 border border-matrix-green/20 text-[11px] text-emerald-200/90 font-mono whitespace-pre-wrap"
   ```

3. **Line 490** (System Prompt `<pre>`) — remove `max-h-60 overflow-y-auto`:
   ```
   className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-xs text-slate-300 font-mono whitespace-pre-wrap"
   ```

4. **Line 513** (Prompt `<pre>`) — remove `max-h-60 overflow-y-auto`:
   ```
   className="p-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-xs text-slate-300 font-mono whitespace-pre-wrap"
   ```

5. **Line 541** (Response `<pre>`) — remove `max-h-80 overflow-y-auto`:
   ```
   className="p-3 rounded-lg bg-slate-800/50 border border-matrix-green/20 text-xs text-matrix-green/80 font-mono whitespace-pre-wrap"
   ```

All four `<pre>` blocks keep `whitespace-pre-wrap` so long lines still wrap (horizontal overflow stays fine). The outer `ScrollArea` at line 284 handles all vertical scrolling uniformly.

## Why this is the right shape (vs alternatives)

- **Make inner pres scroll "correctly" via `overscroll-contain`** — still leaves two scrollbars stacked and creates the same "where do I scroll?" confusion. Rejected.
- **Make the whole DialogContent `overflow-y-auto` like CreateProjectDialog** — loses the Radix ScrollArea styled scrollbar (matrix-green theme); also removes the ability to pin a footer later. Rejected.
- **Keep inner scrolls, add `flex-shrink-0` on header only** — doesn't solve the wheel-capture UX problem the user actually hit. Rejected.

## Verification

Docker rebuild (per CLAUDE.md — no asking, just rebuild):
```
docker-compose build legion-frontend && docker-compose up -d legion-frontend
```

Manual browser test (http://localhost:3005/llm):
1. Open LLM Console, click any recent call row → modal opens
2. Pick a call whose System Prompt + Prompt + Response are all long (the screenshot's call is a good candidate: 1107 input / 157 output tokens)
3. With pointer hovering over the **Response** block (previously the most-offending nested scroller), spin the mouse wheel — the outer modal should advance smoothly past the bottom of the Response
4. Repeat with pointer over System Prompt and Prompt blocks
5. Confirm the matrix-green Radix scrollbar on the right tracks one continuous scroll from metadata grid at top → Est. Cost → Quality Review → System Prompt → Prompt → Response → last line
6. Close modal, open a call with SHORT content — scrollbar should not appear when content fits

Type check (per CLAUDE.md):
```
cd frontend && npm run build
```

No new components, no new hooks, no API changes — the diff is className-only so type check should be green.
