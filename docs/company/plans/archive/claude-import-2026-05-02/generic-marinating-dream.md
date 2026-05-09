# Character Content Pipeline - Comprehensive Review & Enhancement Plan

## Context
The Character Content system is a 5400-line pipeline generating TikTok carousels from character research. The screenshot shows characters stuck on "Fact Mining" at 28% overall progress. After reviewing every layer (backend services, LLM routing, prompts, concurrency, frontend), I found 6 categories of issues ranging from critical bottlenecks to quality-of-life improvements.

---

## Phase 1: Concurrency & Bottleneck Fixes (Immediate wins)

### 1A. Bump Ollama Semaphore from 1 to 2
- **File**: [character_content_service.py:149](backend/app/services/character_content_service.py#L149)
- **Why**: `_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)` serializes ALL LLM work. With 3 characters researching in parallel, synthesis alone = 240s * 3 = 720s serialized. Bumping to 2 cuts this to ~360s.
- **Risk**: GPU VRAM pressure. qwen3.6:35b uses ~20GB; two concurrent inference calls need headroom. Test with `nvidia-smi` monitoring.
- **Also**: Make configurable via settings (`OLLAMA_CONCURRENCY` in [config.py](backend/app/infrastructure/config.py))

### 1B. Parallelize SearXNG Searches
- **File**: [character_content_service.py:564-594](backend/app/services/character_content_service.py#L564)
- **Current**: 5-6 queries run in a sequential `for` loop (~15s total)
- **Fix**: `asyncio.gather(*[searxng.search(q, num_results=8) for q in queries])` (~3-5s)

### 1C. Reuse aiohttp.ClientSession in Wiki Scraping
- **File**: [character_content_service.py:621](backend/app/services/character_content_service.py#L621)
- **Current**: Creates `async with aiohttp.ClientSession()` inside the `for url in wiki_urls[:2]` loop
- **Fix**: Create one session outside the loop, pass it in

### 1D. Reduce Research Queue Polling
- **File**: [useCharacterContentApi.ts:~1095](frontend/src/hooks/useCharacterContentApi.ts)
- **Current**: `refetchInterval: enabled ? 2000 : false` (2s)
- **Fix**: Change to 5000ms. Research steps take 15-240s each; 2s polling is wasteful.

### 1E. Fix Fallback Carousel Hook
- **File**: [character_content_service.py:1279](backend/app/services/character_content_service.py#L1279)
- **Current**: `"hook_text": f"What they don't tell you about {name}..."` - this IS a banned hook pattern
- **Fix**: Use highest surprise_score fact from `filtered_facts[0]["text"]` as fallback hook

---

## Phase 2: Model Strategy Overhaul

### 2A. Split `character_research` into Distinct Task Types
- **File**: [router_config.json](workspace/llm/router_config.json)
- **Problem**: Synthesis, fact extraction, and carousel generation ALL use `task_type="character_research"` (same model, same routing). They have very different needs.
- **Add new task assignments**:
  - `character_synthesis` - Ollama primary, temp 0.3, 16384 tokens (accuracy-focused)
  - `character_fact_extraction` - Ollama primary, temp 0.2 (lower than current 0.4, more deterministic)
  - `character_carousel_generation` - **MiniMax M2.7 or Kimi K2 primary** with Ollama fallback, temp 0.8 (creative writing is the one task that most benefits from a stronger model)
- **Code changes**: Update task_type strings at lines 689, 798, 1233 in character_content_service.py

### 2B. Fix Stage 2 Final Review Routing
- **File**: [router_config.json](workspace/llm/router_config.json) line ~130
- **Problem**: `character_content_review_final` currently defaults to `ollama/qwen3.6:35b-a3b-q8_0`. Stage 2's entire purpose is a different model's perspective. Using the same model as Stage 1 adds latency without independent signal.
- **Fix**: Change primary to `minimax/MiniMax-M2.7` with Kimi fallback. Ollama as last resort.

### 2C. Route Carousel Generation Through Unified LLM Client
- **File**: [character_content_service.py:1229-1238](backend/app/services/character_content_service.py#L1229)
- **Current**: `self._ollama.chat(...)` bypasses the entire unified_llm_client routing/fallback/budget system
- **Fix**: Replace with `get_unified_llm_client().chat(task_type="character_carousel_generation", ...)`. This enables the cloud provider fallback chain and budget controls.

---

## Phase 3: Prompt Engineering

### 3A. Expand RESEARCH_SYSTEM_PROMPT
- **File**: [character_content_service.py:175-177](backend/app/services/character_content_service.py#L175)
- **Current**: 3 lines of generic instruction
- **Enhance**: Add guidance on prioritizing lesser-known facts, cross-referencing sources, distinguishing between confirmed canon and fan speculation. Specify that "good" means facts a casual fan wouldn't know.

### 3B. Add Scoring Rubric to AI_REVIEW_PROMPT
- **File**: [character_content_service.py:313-338](backend/app/services/character_content_service.py#L313)
- **Problem**: No calibration for what scores mean. Models drift toward 6-7 for everything.
- **Fix**: Add explicit rubric:
  - 9-10: "Would go viral. Hook is unique, facts unknown to 95% of fans"
  - 7-8: "Strong content, one dimension needs sharpening"
  - 5-6: "Publishable but forgettable"
  - 1-4: "Not publishable, major issues"

### 3C. Remove Stage 1 Scores from FINAL_REVIEW_PROMPT
- **File**: [character_content_service.py:1817-1819](backend/app/services/character_content_service.py#L1817)
- **Problem**: Passing Stage 1 scores creates anchoring bias. Stage 2 reviewer adjusts slightly from Stage 1 instead of evaluating independently.
- **Fix**: Remove `stage1_scores` from the prompt template. After both reviews, compute weighted composite in code.

### 3D. Add Per-Angle Hook Examples
- **Problem**: Hook examples in CAROUSEL_GENERATION_PROMPT (line 233) are hardcoded (always same 4). Model pattern-matches.
- **Fix**: Create a hook example bank organized by angle. Inject 3-4 examples matching the requested angle at generation time. Add to `character_content_utils.py` or a new `carousel_examples.py`.

### 3E. Angle-Specific Tone Instructions
- **Problem**: `dark_facts` and `origin_story` use identical system prompts. A dark facts carousel should be provocative; origin story should be dramatic/cinematic.
- **Fix**: Add angle-specific tone snippets appended to CAROUSEL_SYSTEM_PROMPT at generation time.

### 3F. Fact Extraction Quality Tiers
- **File**: [character_content_service.py:179-205](backend/app/services/character_content_service.py#L179)
- **Fix**: Add explicit tier definitions and deduplication instruction: "Do not include facts common to casual fans (e.g., 'Batman's parents were murdered'). Prioritize facts that would make a TikTok viewer stop scrolling."

---

## Phase 4: Pipeline Architecture Hardening

### 4A. Retry-With-Simpler-Prompt Strategy
- **File**: [character_content_service.py:1267-1286](backend/app/services/character_content_service.py#L1267)
- **Current**: JSON parse fails -> static fallback template
- **Fix**: Add intermediate retry with simplified prompt (reduce slide count to 4, remove brain context, add explicit "OUTPUT ONLY JSON" instruction) before falling to static fallback.

### 4B. Exponential Backoff for needs_retry
- **Current**: `needs_retry` status exists but no backoff. Characters get retried immediately and can loop forever.
- **Fix**: Add `retry_count` tracking. Delay = min(2^retry_count * 60, 3600)s. After 5 retries, mark `failed_permanent`.

### 4C. Decouple Generation from Review
- **Current**: `generate_carousel()` at line 1388-1389 auto-triggers `ai_review_carousel()`. Both acquire `_OLLAMA_SEMAPHORE`, doubling wait time.
- **Options**: (a) Don't auto-review during generation; let the scheduler job handle it in batches. (b) Review asynchronously via background task. Recommend (b): `asyncio.create_task(self.ai_review_carousel(carousel_id))` instead of awaiting.

### 4D. Carousel Deduplication
- **Before generating**: Check if a carousel exists for same character + angle within last 7 days. If so, either skip or rotate to a different angle from `_get_underused_angles()`.

---

## Phase 5: Frontend Enhancements

### 5A. Show Review Reasoning
- **File**: [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx)
- **Problem**: Review scores are shown but `suggestions`, `polish_suggestions`, `fact_check_flags`, and `verdict` are hidden.
- **Fix**: Add expandable "Review Details" section showing per-dimension scores, suggestions, and Stage 2 verdict. This helps human reviewers make faster decisions.

### 5B. ETA Range Display
- **Current**: Simple average ETA. Infrastructure for p50/p95 exists in `_step_stats_cache`.
- **Fix**: Surface "estimated 3-8 min" range instead of "ETA 5m 23s" point estimate.

### 5C. Component Decomposition (Lower Priority)
- CharacterContentPage.tsx (1967 lines) should be split into tab-level components: `CharactersTab`, `ResearchQueueTab`, `ContentStudioTab`, `ReviewQueueTab`, etc. under `frontend/src/components/character-content/`.

---

## Phase 6: Quality Loop Enhancements

### 6A. Hook Style Performance Tracking
- Track engagement metrics by `hook_style`. After n > 20 per style, weight selection toward better performers in `smart_batch_generate`.

### 6B. Score Calibration Set
- Store 10-15 hand-scored example carousels. Include 2-3 as calibration examples in review prompts to ground scoring and prevent drift.

---

## Verification Plan
1. **Semaphore change**: Run batch research of 6 characters. Measure wall-clock time before vs after. Monitor GPU with `nvidia-smi -l 1`.
2. **Search parallelization**: Log step timings for `searxng_search` step. Should drop from ~15s to ~3-5s.
3. **Model routing**: Check `generation_metadata.model` on new carousels to confirm they route through the intended provider.
4. **Prompt improvements**: Generate 10 carousels with old vs new prompts. Compare AI review scores and hook diversity (unique hooks / total hooks).
5. **Frontend polling**: Check network tab in browser devtools. Should see /research-queue requests every 5s instead of 2s.
6. **Fallback hook**: Trigger a generation failure (e.g., disconnect Ollama briefly). Verify fallback carousel doesn't use banned hook.

## Implementation Order
Phase 1 (concurrency fixes) -> Phase 2 (model routing) -> Phase 3 (prompts) -> Phase 4 (pipeline hardening) -> Phase 5 (frontend) -> Phase 6 (quality loop)

Each phase can be deployed independently. Phase 1 alone should noticeably speed up the "Stuck on Fact Mining" issue visible in the screenshot.
