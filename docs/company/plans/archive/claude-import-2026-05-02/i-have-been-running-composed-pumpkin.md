# Reachy Companion Personalities + Growing Memory

## Context

You've been running Reachy in interactive mode and none of the 13 shipped personas work as a companion or PA. The catalog is all "character voices" — the default `cosmic_kitchen` forces a food pun every reply, `mars_rover` is allowed to use "mild foul language" and types in ALL CAPS, `sorry_bro` is explicitly designed to mock you, `mad_scientist_assistant` calls you "Master" and hisses, `bored_teenager` does passive-aggressive sighs, etc. They're built for demos, not for someone you actually live with.

Three things to fix:
1. **Persona catalog** — nuke the bit personas, ship 7 normal ones (companion, PA, deep-work partner, coach, wellness, narrator, curious explorer).
2. **Persistent memory** — the infra is already 80% there (turn logging, LLM extraction every 5 turns, JSON store, pgvector embeddings, Obsidian vault writer/indexer). It's just not being used as a single coherent memory model. Adopt Letta's memory-block pattern (persona / human / relationship / working_context) and run it inside the existing voice loop.
3. **Personality growth** — nightly synthesis job that reads the last 24h of turns + vault writes + current blocks, updates the `human_block` and `relationship_block`, and writes a dated snapshot to `00_Meta/_agent/reachy/personality-history/` so you can read, edit, or roll back what Reachy has learned.

### About the Letta question

Full Letta integration would be a downgrade for voice + gesture, not an upgrade. Letta is a **text-only** agent runtime — it has no audio path. To use it for voice you'd put LiveKit or Vapi in front (third-party voice platforms that handle audio I/O), then route text through Letta. Concretely you'd lose:
- Direct OpenAI Realtime / Gemini Live (<300 ms turn latency) — replaced by LiveKit/Vapi → Letta → LLM hop chain.
- Inline gesture markers `[emotion:happy]` interleaved with speech — Letta's tool calls are sequential, so gestures would batch at end-of-turn.
- The existing intent router, host_agent supervision, speaker sink, wobbler integration, OBS overlay, etc.

What Letta has that we want is the **memory-block model**: tiny named blocks (persona, human, recall, archival) that compose into the system prompt, that the agent itself can self-edit via tool calls. That model is ~300 lines of code. We'll borrow it and run it inside our existing voice loop. The result: same realtime voice + gestures we have now, plus Letta-quality memory.

## Critical files

**Backend (replace / extend):**
- [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py) — replace the 13-persona catalog
- [backend/app/data/reachy_profiles/](backend/app/data/reachy_profiles/) — delete 13 directories, create 7 new
- [backend/app/services/voice_loop_service.py](backend/app/services/voice_loop_service.py) — change default persona, swap prompt assembly to use memory blocks (lines 74, 269-288, 439-514)
- [backend/app/services/reachy_realtime/profiles.py](backend/app/services/reachy_realtime/profiles.py) — same prompt assembly change for realtime path (lines 196-207)
- [backend/app/services/reachy_user_memory_service.py](backend/app/services/reachy_user_memory_service.py) — keep turn log + extractor, retire `_notes` JSON in favor of memory blocks
- [backend/app/services/reachy_context_service.py](backend/app/services/reachy_context_service.py) — output as `working_context_block` instead of inlining

**Backend (new):**
- `backend/app/services/reachy_memory_blocks.py` — block store + composer + self-edit tool
- `backend/app/services/reachy_personality_synthesis_service.py` — nightly synthesizer
- `backend/app/routers/reachy_memory.py` — block CRUD + history list endpoints

**Existing infra to reuse (do not reinvent):**
- [backend/app/services/vault_retrieval_service.py](backend/app/services/vault_retrieval_service.py) — `search()` returns BM25+dense hits, RRF-fused; partition-aware
- [backend/app/services/vault_writer_service.py](backend/app/services/vault_writer_service.py) — `write_agent_file()` writes to `00_Meta/_agent/**` with audit footer
- [backend/app/infrastructure/ollama_client.py](backend/app/infrastructure/ollama_client.py) — `embed_safe()` for any embedding
- [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py) — APScheduler hooks (66 jobs already running)
- [backend/app/services/unified_llm_client.py](backend/app/services/unified_llm_client.py) — already routes to kimi-heavy / gemini-pro for synthesis-grade calls

**Frontend:**
- [frontend/src/components/reachy/InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) — persona dropdown
- [frontend/src/components/reachy/LLMStatusBadge.tsx](frontend/src/components/reachy/LLMStatusBadge.tsx) — leave alone
- New page `frontend/src/pages/ReachyMemory.tsx` — view + edit blocks, browse history snapshots

## Phase 1 — New persona catalog (full nuke + replace)

Delete from [backend/app/services/reachy_personas.py](backend/app/services/reachy_personas.py): all 13 personas (`bored_teenager`, `captain_circuit`, `chess_coach`, `cosmic_kitchen`, `hype_bot`, `mad_scientist_assistant`, `mars_rover`, `nature_documentarian`, `noir_detective`, `sorry_bro`, `time_traveler`, `victorian_butler`, `attentive_colleague`). Delete the matching directories under [backend/app/data/reachy_profiles/](backend/app/data/reachy_profiles/) including the upstream `tedai` event profile.

Replace with seven personas, all sharing a **core-identity preamble** (you are Zero, embodied in Reachy Mini, a small expressive robot; speak briefly because you're a voice; fire gestures inline with `[emotion:X]` / `[dance:Y]`):

| ID | Name | Voice (Edge-TTS) | Role |
|----|------|------------------|------|
| `companion` (default) | Companion | `en-US-AriaNeural` | Warm, present, curious about your day. Listens more than talks. Remembers what you care about. |
| `assistant` | Assistant | `en-US-AndrewNeural` | Competent J.A.R.V.I.S-style PA. Calendar and task aware, dry wit, no fluff. |
| `deep_work` | Deep Work Partner | `en-US-EricNeural` (low volume) | Silent unless directly addressed. Shortest possible reply. Never breaks flow. |
| `coach` | Thinking Partner | `en-GB-RyanNeural` | Socratic. Asks one good question back instead of lecturing. |
| `wellness` | Check-in | `en-GB-SoniaNeural` | Gentle end-of-day reflection. Helps name feelings, never preachy, never tries to fix. |
| `narrator` | Narrator | `en-US-BrianNeural` | Daily recap, retrospectives. Reads your journal + notes, asks one noticing question. |
| `explorer` | Curious Explorer | `en-US-ChristopherNeural` | Playful, intellectually stimulating. Surfaces non-obvious connections. |

Each persona is a `Persona` dataclass row + an `instructions.txt` in `backend/app/data/reachy_profiles/<id>/`. Each `instructions.txt` is ≤180 words: identity → tone → length rule → what NOT to do. No food puns, no all-caps, no hissing, no mocking. Keep gesture markers in the existing `MOTION_TAG_INSTRUCTIONS` block — those work and are persona-orthogonal.

Default in [voice_loop_service.py:74](backend/app/services/voice_loop_service.py#L74) flips from `"cosmic_kitchen"` to `"companion"`.

## Phase 2 — Memory blocks (Letta-style, run locally)

New service `backend/app/services/reachy_memory_blocks.py`. Persisted to `workspace/reachy/memory_blocks.json` (keep alongside existing `user_memory.json` and `persona_state.json`).

```python
@dataclass
class MemoryBlock:
    label: str                    # persona | human | relationship | working_context
    value: str                    # the block text
    max_chars: int                # hard cap for prompt budget
    last_updated_by: str          # "user" | "reachy" | "synthesis_job"
    last_updated_at: datetime
    edit_history: list[Edit]      # last N edits for rollback
```

**Four blocks composed into every system prompt** (in this order, after core identity, before gesture instructions):

1. **persona_block** — active persona's `instructions.txt` plus any persistent user-driven tweaks ("user prefers I skip greetings"). Editable by user via the memory page; only Reachy can append a tweak via tool call.
2. **human_block** — ≤500 words of durable facts about you (name, work, recurring projects, communication preferences, what matters). Migrated on first run from existing `user_memory.json` `_notes` via a one-shot LLM compaction. Updated nightly + on-demand.
3. **relationship_block** — ≤300 words of shared shorthand: recurring topics, inside jokes, recent threads. Built nightly from the last 7 days of turns.
4. **working_context_block** — generated fresh per turn from [reachy_context_service.py](backend/app/services/reachy_context_service.py): time, calendar, pomodoro, meeting state, sight context, attention alerts, **+ top-3 vault chunks matching the current user text** (new — see Phase 3).

**Self-edit tool** exposed to both classic and realtime paths:
```
update_memory_block(block: "human" | "relationship", patch: str, reason: str)
```
Reachy calls this when it learns something important ("user just told me their daughter's name is Mira"). Every edit is logged with timestamp + reason, viewable + revertable on the memory page. Block label `persona` is **read-only to the model** — only the user or the nightly synthesis job can write it.

System prompt assembly in `voice_loop_service._get_llm_response()` (lines 439-514) and `reachy_realtime/profiles.resolve_instructions()` (lines 205-207) both go through a single new `compose_system_prompt(persona_id, user_text) -> str` helper so classic and realtime stay in sync.

## Phase 3 — Vault retrieval into the voice loop

Wire the existing Obsidian indexer into Reachy. Currently `vault_retrieval_service.search()` is exposed via MCP and used by orchestration but never queried from the voice path.

**Classic path** ([voice_loop_service.py:439](backend/app/services/voice_loop_service.py#L439)): right before `compose_system_prompt`, call `vault_retrieval_service.search(user_text, k=3, partitions=["projects","reference","journal"])`. RRF + journal time-decay are already implemented. Inject hits into `working_context_block` as a `### RELATED FROM YOUR NOTES` section with file path + 1-line excerpt per hit (~600 chars budget total).

**Realtime path** (OpenAI Realtime / Gemini Live): system instructions are locked at session start, so we use two hooks:
1. **Pre-warm at user turn start** — handler intercepts the audio commit, runs partial STT (already happening for transcript events), fires the same vault search, sends a `session.update` with the chunks appended to instructions. ≤300 ms overhead, runs in parallel with the LLM's first token.
2. **Tool fallback** — register a `lookup_my_notes(query: str)` tool the model can call mid-conversation when it wants more context than the pre-warm fetched. Hits the same `vault_retrieval_service.search()`.

## Phase 4 — Personality growth (nightly synthesis)

New service `backend/app/services/reachy_personality_synthesis_service.py`. New scheduler job `reachy_personality_synthesis_tick` registered in [scheduler_service.py](backend/app/services/scheduler_service.py), cron 02:30 daily (after the existing 02:15 drift scan).

Pipeline:
1. Read last 24 h of turns from `reachy_user_memory_service` (`_turns` ring buffer) + current `human_block` + current `relationship_block` + any vault writes the agent made today.
2. Single call to **kimi-heavy** (preferred — top reasoning quality, low rate-limit pressure overnight) with a structured prompt that asks for: (a) updated human_block, (b) updated relationship_block, (c) one paragraph "what I noticed today," (d) any low-confidence drafts that should be marked for user review.
3. Apply updates atomically via `MemoryBlockStore`. Log diff.
4. Write snapshot via `vault_writer_service.write_agent_file()` to `00_Meta/_agent/reachy/personality-history/2026-04-27.md` with frontmatter (date, blocks_before_hash, blocks_after_hash) and body (what changed, what was noticed, draft items needing review).
5. If any draft items, raise an `agent_alerts` row with `rule="reachy_personality_review"` so it surfaces in tomorrow's morning digest.

Compaction: synthesizer also re-emits the existing `user_memory.json` `_notes` ring as a digest into the human_block, then truncates the ring to the most recent 100 turns. Stops the unbounded growth pattern noted in the existing `compact()` method.

## Phase 5 — Frontend

Persona picker rebuild in [InteractiveModeBar.tsx](frontend/src/components/reachy/InteractiveModeBar.tsx) (and the desktop-mode picker if it differs): two-column card grid, 7 cards, with name + voice preview + tagline. No category split — seven is small enough to show flat.

New page `frontend/src/pages/ReachyMemory.tsx` accessed from the Reachy section sidebar. Three panes:
1. **Blocks** — text editor for `persona`, `human`, `relationship`. Save button calls new `PUT /api/reachy/memory/blocks/{label}` endpoint. Char counter + max_chars cap shown.
2. **Recent edits** — last 30 edits across all blocks with who/when/why and a per-edit revert button.
3. **History** — list of personality-history snapshot files from the vault, click to view (read-only, opens via existing vault file endpoint).

New router `backend/app/routers/reachy_memory.py` exposes the block CRUD + history list. All endpoints behind `Depends(require_auth)`.

## Phase 6 — Verification

End-to-end test (run after rebuild):
1. `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api && docker compose -f docker-compose.sprint.yml restart zero-ui`
2. Open Reachy interactive mode, confirm default is **Companion**, voice is Aria, no food puns appear in the first 5 turns. Speak a few real-life things ("I'm tired, what's on tomorrow") and check the reply tone — warm, brief, references your calendar.
3. Switch through all 7 personas via the picker, verify each behaves on-brand for one turn.
4. Open `workspace/reachy/memory_blocks.json` — confirm `human_block` was migrated from old `user_memory.json` notes.
5. Tell Reachy a memorable fact ("my dog's name is Mira"). Confirm it calls `update_memory_block(block="human", ...)` (visible in `docker logs zero-api`) and the fact lands in the `human_block` JSON.
6. Trigger the nightly synthesizer manually: `docker exec zero-api python -m app.services.reachy_personality_synthesis_service --run-now`. Verify a snapshot lands at `C:\code\vault\ObsidianZero\00_Meta\_agent\reachy\personality-history\2026-04-27.md`.
7. Ask Reachy about something you wrote in your vault yesterday. Verify the `working_context_block` contains a `### RELATED FROM YOUR NOTES` section by checking `docker logs zero-api | grep "system_prompt_composed"`.
8. Open `/reachy/memory` in the frontend, confirm blocks render, edit `human_block`, save, hard-refresh, confirm persistence.
9. Browser check: open the persona picker, confirm seven cards, no Cosmic Kitchen / Mars Rover / Sorry Bro anywhere.

## Out of scope (deliberately)

- Full Letta integration (would lose realtime voice + inline gestures — explained in Context).
- Replacing user_memory's turn extractor (it works; we just stop persisting `_notes` separately and route through `human_block` instead).
- Multi-user support (current user_profile is singleton id=1; keep it).
- Voice cloning / custom TTS voices (Edge-TTS voices are good enough for now).
