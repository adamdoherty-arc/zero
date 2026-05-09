# Prompt Evolution Log

Tracks prompt mutations, hook performance, and template effectiveness over time.
Inspired by PromptBreeder (Google DeepMind) and OpenAI Self-Evolving Agents.

## Mutation 2026-04-19: Retry Prompt Placeholder Leak

**Problem**: 2 draft carousels (Batman `cc-64057fac44a6`, Last Chef Standing `cc-8906ea145181`) persisted with literal placeholder strings as slide text: "hook text", "fact 1", "fact 2", "CTA". Hook text was "scroll-stopping first line about Batman" — the prompt instruction itself.

**Root cause**: [character_content_service.py:1501-1509](backend/app/services/character_content_service.py#L1501) simpler-retry prompt used literal placeholder strings as its JSON schema example ("hook text", "fact 1", "short title"). Qwen3 echoed the schema back instead of substituting content. `sanitize_carousel` did not detect these placeholder tokens.

**Fix (this session)**:
1. Rewrote retry prompt: schema example now uses `<angle-bracketed descriptors>` (e.g. `<fact rewritten, 10-25 words>`) instead of literal strings that look like real content.
2. Added placeholder token guard after retry parse: if any slide text / hook / title matches a known template token set (`hook text`, `fact 1..5`, `short title`, `cta`, `caption with emojis`), drop the retry result and fall through to the static fact-based fallback instead of persisting junk.
3. Rejected the 2 existing broken carousels via API.

**Verification**: Backend rebuilt + healthy. Next scheduler run (00:00 UTC) will exercise the new path. Watch for `carousel_generation_retry_returned_placeholders` log entries as a signal the guard is firing.

## Hook Style Performance

| Style | Requested | Times Generated | Avg AI Score | Trend |
|-------|-----------|----------------|-------------|-------|
| story_opener | 4 | 4 (Thor, Indiana Jones, Eren Yeager, Rocky) | pending review | baseline |
| reveal | 4 | 4 (Wolverine, Jules Vaughn, Luigi, Tyler Durden) | pending review | baseline |
| hot_take | 2 | 2 (Deadpool, Billy Butcher) | pending review | baseline |
| question | 3 | 3 (Neo, Rue Bennett, Lois) | pending review | baseline |
| numbered_list | 3 | 3 (John Wick, Faith MacCaulley, Malcolm) | pending review | baseline |
| comparison | 2 | 2 (Superman, Hughie Campbell) | pending review | baseline |
| superlative | 2 | 2 (Hannibal Lecter, Grace MacCaulley) | pending review | baseline |

**NOTE**: hook_style is NOT being persisted in generation_metadata (all show null). The parameter is accepted by the endpoint but the service doesn't save it. This is a code bug to fix.

## Template Performance

| Template | Avg Score | Times Used | Characters |
|----------|-----------|------------|------------|
| secrets_revealed | -- | 8 | Darth Vader x4, Aquaman, Tyler Durden, Grace MacCaulley |
| dark_origin | -- | 5 | Darth Vader, Thor, Hannibal Lecter, Faith MacCaulley |
| actor_behind_role | -- | 4 | Wolverine, Jules Vaughn, Luigi |
| timeline_story | -- | 2 | Superman, Eren Yeager |
| hot_take | -- | 2 | Deadpool, Billy Butcher |
| deleted_scenes | -- | 2 | Indiana Jones, Malcolm |
| fan_theory_deep_dive | -- | 1 | Neo |
| real_life_inspiration | -- | 2 | John Wick, Rocky |
| hidden_connection | -- | 1 | Hughie Campbell |
| what_they_changed | -- | 2 | Batman, Lois |
| timeline_tragedy | -- | 2 | Loki, Rue Bennett |
| storyline_recap | -- | 1 | Ellie Williams |

## Batch Run: 2026-04-17

- **Model**: ollama/qwen3.6:35b-a3b-q8_0 (carousel generation routed through Ollama, not MiniMax as expected)
- **Characters**: 20 new carousels generated for previously unserved characters
- **Duration**: ~40-230s per carousel (avg ~100s)
- **Success rate**: 20/22 attempts (2 required retry - Grace MacCaulley, Lois)
- **Retry cause**: Empty responses on first attempt (race with Ollama semaphore under research queue load)
- **Quality observations**:
  - Hooks are specific and character-relevant (no generic patterns detected)
  - Fact selection prioritizes high surprise scores (8-10)
  - Some "other" universe characters (Grace, Rocky, Luigi) generated AI-confabulated facts (not grounded in real media)
  - Slide count consistently 6 as requested

## Prompt Mutations

*No mutations yet. AI reviews blocked by Ollama circuit breaker (research queue saturating). Will score and mutate after research queue completes.*

## Auto-Generation Scheduler Verification (2026-04-17 22:21-22:26 UTC)

Triggered scheduler job `character_content_generation` manually to verify end-to-end behavior:
- Job completed in ~4.5 min with `generated=10, failed=0`
- Carousels: 37 -> 47
- Rotated angle across: character_evolution (x3), power_secrets (x2), what_if (x2), hidden_truths, fan_theories, behind_scenes
- Characters: Akuma, Albus Dumbledore, Ant-Man, Aragorn, Arthur Morgan, Billy Butcher, Cammy, Captain Marvel, Chani, Charlie Cannon

**Hook/template tracking gap persists**: scheduler `_run_character_content_generation` calls `svc.generate_carousel(CarouselCreate(character_id=char.id, angle=angle))` only. No `story_template` or `hook_style` passed. Fix = thread a rotation plan through the scheduler node (see [scheduler_service.py](backend/app/services/scheduler_service.py#L2470-L2518)) and persist hook_style in generation_metadata on the service side.

## Evolution Rules

1. Score threshold for promotion: 75% of graders passing OR avg score >= 7.5
2. Max retry attempts per mutation: 3
3. Always keep rollback version
4. Log reason for each mutation
