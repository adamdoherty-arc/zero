# Research Queue: Live Timers + Clickable Detail + Stuck Detection + Deeper Research

## Context

The Research Queue tab shows character research jobs with a 7-step stepper. Two issues:

**UX Problems (from screenshot):**
- Deadpool shows "researching" but all 7 step dots are gray — no indication of what's happening or what's stuck
- Elapsed time is a tiny gray `Clock 0s` text that only updates on 2s poll, not a live ticker
- Job cards are NOT clickable — detail is hidden behind clicking tiny 5px dots
- No stuck detection or warning
- No way to retry a stuck/failed job

**Research Depth Problem:**
- Currently 5 sources: Fandom Wiki, Reddit, TV Tropes, IMDB trivia, Quotes
- Firecrawl is now available but only used for Fandom + TV Tropes + IMDB
- Missing: behind-the-scenes articles, character analysis blogs, Screen Rant/CBR listicles, Wikipedia (proper deep scrape vs just API), comic book databases
- With Firecrawl working, we should scrape more sites to get richer facts

---

## Part A: Frontend UX Improvements

### A1. Live Ticking Timer (`useLiveTimer` hook)
**File**: [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)

Add a tiny custom hook that ticks every second when a job is active:
```tsx
function useLiveTimer(active: boolean) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [active])
}
```

In `ResearchJobCard` (line 546):
- Call `useLiveTimer(isActive)` to re-render every second
- Replace the small gray elapsed text with a prominent timer badge:
  - Active: amber bg, bold text, `Timer` icon, ticking `2m 34s`
  - Completed: green bg, final duration
  - Failed: red bg, duration at failure

In `ResearchStepStepper` (line 631):
- The running step's duration (line 665-668) already computes live but only updates on poll — with `useLiveTimer` called at the parent, it will now tick every second

### A2. Clickable Expandable Job Cards
**File**: [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)

Modify `ResearchJobCard` (line 546):
- Add `const [expanded, setExpanded] = useState(false)` — auto-expand if `isActive`
- Make the card header clickable: `onClick={() => setExpanded(!expanded)}`
- Add `ChevronDown`/`ChevronUp` icon on the right side
- Add cursor-pointer styling

**Expanded panel** (below the stepper, inside the card):
```
┌─ Step Timeline ──────────────────────────────────────────┐
│ Step              Status     Duration   Result            │
│ ─────────────     ────────   ────────   ──────────────── │
│ Web Search        ✓ done     12s        15 results        │
│ Wikipedia         ✓ done     8s         2 wiki pages      │
│ Deep Sources      ● running  1m 42s     ⚠ Possibly stuck │
│ AI Synthesis      ○ pending  -          -                 │
│ Fact Mining       ○ pending  -          -                 │
│ Image Search      ○ pending  -          -                 │
│ Saving            ○ pending  -          -                 │
└──────────────────────────────────────────────────────────┘
│ Sources: fandom_wiki (12 frags), reddit (5), tvtropes (1)│
│ Error: (none)                                             │
```

Each row in the step table is clickable → opens the existing step detail `Dialog` (reuse existing modal at line 700-765).

### A3. Stuck Detection
**File**: [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)

In `ResearchJobCard`:
```tsx
const runningStep = job.steps?.find(s => s.status === 'running')
const stepElapsedSec = runningStep?.started_at
  ? Math.floor((Date.now() - new Date(runningStep.started_at).getTime()) / 1000)
  : 0
const isStuck = runningStep && stepElapsedSec > 120  // 2 min threshold
```

Visual indicators:
- Step dot: running step > 2min → change from indigo pulse → amber pulse
- Job card: Show amber `AlertTriangle` "Possibly stuck" badge next to status badge
- Expanded view: Show warning banner with duration and step name
- Add a **Retry** button when stuck or failed

### A4. Retry Button
**File**: [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)

On failed or stuck job cards, show:
```tsx
<Button size="sm" variant="outline" onClick={() => retryMutation.mutate(job.character_id)}>
  <RotateCcw className="w-3 h-3 mr-1" /> Retry
</Button>
```

---

## Part B: Backend Retry Endpoint

### B1. Retry Research Job
**File**: [character_content.py](backend/app/routers/character_content.py)

New endpoint:
```python
@router.post("/research-queue/retry/{character_id}")
async def retry_research_job(character_id: str):
```

### B2. Service Method
**File**: [character_content_service.py](backend/app/services/character_content_service.py)

New method `retry_research_job(character_id)`:
- Reset the job in `_research_queue["jobs"]` if it exists (reset steps to pending, status to "queued")
- If queue is still running, insert at front of `_research_queue["order"]`
- If queue is not running, start a new single-job queue
- Return updated queue status

---

## Part C: Deeper Research Sources (Firecrawl)

### C1. Add 3 New Research Sources
**File**: [character_research_sources.py](backend/app/services/character_research_sources.py)

Add to `research_from_all_sources()` (line 121-127):

| # | Source | Method | What It Scrapes |
|---|--------|--------|-----------------|
| 6 | **Screen Rant / CBR** | SearXNG finds article URLs → Firecrawl scrapes | Character listicles, "Things you didn't know about X", behind-the-scenes articles |
| 7 | **Wikipedia (deep)** | Firecrawl scrapes full Wikipedia article | Full biography, production history, reception sections — much richer than the existing SearXNG snippet approach |
| 8 | **Comic Vine / SuperheroDB** | SearXNG finds page → Firecrawl scrapes | Power rankings, first appearances, team affiliations, alternate versions |

#### Source 6: `research_entertainment_articles(name, universe, franchise)`
- SearXNG queries: `"{name}" screenrant.com OR cbr.com facts`, `"{name}" character behind the scenes things you didn't know`
- Filter results for screenrant.com, cbr.com, looper.com, collider.com, denofgeek.com
- Firecrawl-scrape top 3 article URLs
- Extract article body, classify as `behind_scenes` or `trivia`

#### Source 7: `research_wikipedia_deep(name, universe)`
- Firecrawl scrapes `https://en.wikipedia.org/wiki/{Name}_(character)` or `{Name}_({franchise}_character)`
- Falls back to `{Name}_(comics)` or `{Name}_(DC_Comics)` etc.
- Split into sections, extract: Fictional character biography, Powers and abilities, In other media, Cultural impact/Reception
- Much richer than the existing wiki_scrape step which just uses SearXNG search snippets

#### Source 8: `research_power_databases(name, universe)`
- SearXNG finds Comic Vine or SuperheroDB pages
- Firecrawl scrapes for structured data: power grid, first appearance, team affiliations, alternate versions
- Fragment type: `power_stats`

### C2. Update `research_from_all_sources`
**File**: [character_research_sources.py](backend/app/services/character_research_sources.py)

Add the 3 new sources to the `tasks` list at line 121-127:
```python
tasks = [
    self._safe_research(self.research_fandom_wiki, name, universe, franchise),
    self._safe_research(self.research_reddit, name, universe, franchise),
    self._safe_research(self.research_tvtropes, name, universe, franchise),
    self._safe_research(self.research_imdb_trivia, name, franchise),
    self._safe_research(self.research_quotes, name, universe),
    # NEW: Firecrawl-powered deep sources
    self._safe_research(self.research_entertainment_articles, name, universe, franchise),
    self._safe_research(self.research_wikipedia_deep, name, universe),
    self._safe_research(self.research_power_databases, name, universe),
]
```

All 8 sources run in parallel with 25s timeout each.

---

## Part D: Frontend Hook

### D1. Add Retry Mutation
**File**: [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts)

```typescript
export function useRetryResearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (characterId: string) =>
      api.post(`/api/characters/research-queue/retry/${characterId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research-queue'] }),
  })
}
```

---

## Files to Modify

| File | Changes |
|------|---------|
| [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) | `useLiveTimer`, expandable cards, stuck detection, retry button, step timeline table |
| [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) | `useRetryResearch` mutation |
| [character_content.py](backend/app/routers/character_content.py) | `POST /research-queue/retry/{character_id}` endpoint |
| [character_content_service.py](backend/app/services/character_content_service.py) | `retry_research_job()` method |
| [character_research_sources.py](backend/app/services/character_research_sources.py) | 3 new sources: entertainment articles, Wikipedia deep, power databases |

## Verification

1. Start research queue → see **live ticking timer** on active job (updates every second)
2. Click on any job card → **expands** to show step timeline table with per-step results and durations
3. If a step runs > 2 minutes → **amber "Possibly stuck"** badge appears
4. Click **Retry** on a stuck/failed job → job re-queues and processes
5. Research completes with **8 sources** (was 5) → more fragments, higher depth scores
6. Completed jobs show total duration and per-step breakdown when expanded
7. Rebuild zero-api, restart zero-ui, verify all changes deployed
