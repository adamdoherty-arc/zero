# Plan: Run /zero-reachy-audit (full audit, 2026-04-24)

## Context

The user invoked `/zero-reachy-audit` with no flags, which means a **full 6-phase audit** of everything Reachy Mini does inside Zero. The prior audit was **2026-04-23 (overall A, 95/100)** and it flagged one dominant watch item: a massive capability wave (OpenAI Realtime + Gemini Live voice, `reachy_sequence_service`, REQ-002 meeting prep + email voice triage, `meeting_auto_recorder_service`, migration 038) was sitting **uncommitted on the working tree**.

`git log --oneline -20` on main shows **zero Reachy commits since 2026-04-23** — the only new commit is `b05af9a` (the knowledge seed itself). The uncommitted slab has in fact grown: `host_agent/` gained `supervisor.py`, `wake_loop.py`, `whisper_wake_loop.py`, `audio_capture.py`, `voice_capture.py`, `camera_worker.py`, `live_transcription.py`, `main.py`; frontend added `useRealtimeVoice.ts`, `lib/reachy-realtime-audio.ts`, and a vitest for the audio lib; backend gained `reachy_profiles/` per-persona `instructions.txt` + `tools.txt` dirs for 14 personas plus a `reachy_prompts_library/` identity/behavior seed. None of this has landed. REQ-002's 0/7 verification boxes are also unchanged.

So this audit's job is to:
1. Re-inventory (capabilities have expanded again in-tree).
2. Grade the six dimensions and compare to the 2026-04-23 baseline.
3. Do the upstream scan (HF Spaces + Pollen repos).
4. Surface interweavings — the new profile/prompt library opens persona-scoped tool access (new territory).
5. Triage REQ-001 (planned → possibly unblock kickoff) and REQ-002 (still awaiting verify).
6. Persist all state so the next audit's trend arrows are meaningful.

## Recommended approach

Execute the skill exactly as spec'd in `c:\code\zero\.claude\skills\zero-reachy-audit\SKILL.md` — six phases in order, write to each knowledge file on the way out.

### Phase 0 — Load prior state (DONE during planning)

Already read:
- `knowledge/MASTER_SCORECARD.md` — baseline: Motion 98, Voice 96, Persona 98, Presence 97, Meeting 90, Env 92. Overall A (95).
- `knowledge/LEARNINGS.md` — 4 active WATCH items: uncommitted slab, UP-001 shipped without planning transition, Meeting Mode unverified, one-shot voice loop assumption.
- `knowledge/REQUESTS_LOG.md` — REQ-001 `planned`, REQ-002 `integrated-awaiting-verify` (0/7 verify).
- `knowledge/INTEGRATION_IDEAS.md` — 9 hot interweavings (II-001/002/003/004/005/006/007/008/010/011/012), 1 warm (II-009), 1 hot upstream (UP-003 wake word), 1 warm (UP-004 3D viewer, UP-005 MediaPipe). UP-001 and UP-006 archived as shipped.
- `knowledge/CAPABILITIES_MAP.md` — last regen 2026-04-23.
- `knowledge/history/2026-04-22-audit.md` and `2026-04-23-audit.md` both exist.

### Phase 1 — Inventory (1 Explore agent)

Launch **one** Explore agent with the fixed brief from SKILL.md. Since the 2026-04-23 inventory is very recent and I already have the working-tree delta mapped, one agent is sufficient. Brief must add: "Pay special attention to `host_agent/` (supervisor/wake-loop/whisper/camera/live-transcription are new since 2026-04-23), `backend/app/data/reachy_profiles/` and `reachy_prompts_library/` (new per-persona tool/instruction directories), and `frontend/src/lib/reachy-realtime-audio.ts` + `hooks/useRealtimeVoice.ts`. Report deltas vs the current `CAPABILITIES_MAP.md`."

Rewrite `knowledge/CAPABILITIES_MAP.md` with:
- **New rows**: host_agent supervisor + wake loop + whisper wake loop + live transcription, `reachy_profiles/` (14 personas with `instructions.txt` + `tools.txt`), `reachy_prompts_library/` (identities + behaviors), `useRealtimeVoice.ts`, `reachy-realtime-audio.ts` + test.
- **Capability matrix updates**: wake word goes from "scaffold only" → "partial (whisper_wake_loop.py + openwakeword path both exist, neither live-verified)". Add row for per-persona tool grants and prompt library.
- Flag deltas to `LEARNINGS.md` under "Additions this run".

### Phase 2 — Grade six dimensions

For each dimension, run the 4-sub-metric protocol from SKILL.md. Because almost nothing shipped to main and the WATCH item "massive uncommitted slab" escalates, the dominant scoring change this run is **Quality** (not Coverage). The rubric's "uncommitted capability" pattern should deduct quality or freshness points — promote it to a checkable rule if this is the 2nd consecutive audit seeing it (it is).

Predicted directional outcomes (to be confirmed by actual measurement, not asserted):
- **Motion**: still A+ range — clips + sequences + move recorder unchanged on main, but sequences still in-tree only. Flat or slight dip (`→` or `↓ 1–2`).
- **Voice**: A → A- likely. Realtime code grew; still zero commits. Freshness stagnates, quality dings for growing uncommitted surface area.
- **Persona**: the new `reachy_profiles/*/tools.txt` and `reachy_prompts_library/` are coverage *expansion* but also uncommitted. Flat or slight lift in coverage, offset by freshness drag.
- **Presence**: unchanged on main; flat.
- **Meeting Mode**: REQ-002 verify checklist still 0/7, one more audit week of no physical verification. Slight dip (+verification debt).
- **Environment & Integrations**: mostly flat; HA gesture map still unconfigured.

Score each dimension with the documented formula: `coverage*0.40 + quality*0.25 + freshness*0.20 + observability*0.15`. Record trend arrows with 5-point deadband.

### Phase 3 — Upstream ecosystem scan

WebFetch (rate-limited, once per audit):
1. `https://huggingface.co/api/spaces?filter=reachy_mini_python_app&limit=500&full=true` — diff against `knowledge/history/hf_spaces_*.json` if any prior cache exists (first cache will be written this run).
2. `https://api.github.com/users/pollen-robotics/repos?per_page=100&sort=updated` — flag any repo with commits in the last 30 days starting `reachy-mini` or `reachy_mini`.
3. Check release tags on: `openwakeword`, `pollen-robotics/reachy-mini-conversation-app`, `pollen-robotics/reachy_mini_toolbox`, `fcollonval/reachy_mini_wake_word`.

Cache under `knowledge/history/hf_spaces_2026-04-24.json` and `knowledge/history/pollen_repos_2026-04-24.json`. Add new ≥5-likes candidates to `INTEGRATION_IDEAS.md` → *Upstream pickups*.

### Phase 4 — Interweaving synthesis

Four creative prompts. New material for this run:
- **Per-persona tool grants** (new `reachy_profiles/*/tools.txt`) × voice intent router = persona-restricted actions (e.g., `victorian_butler` can read emails but not delete; `hype_bot` can start radio but can't touch Gmail). This is a new II candidate.
- **`reachy_prompts_library/identities/` + `behaviors/`** = compose-from-fragments prompt builder. Could pair with persona rotation to vary identity prompts across sessions.
- **host_agent `wake_loop.py` + `whisper_wake_loop.py`** = local wake word is *almost* live. Combined with REQ-002 email triage, this unlocks hands-free "Reachy, read email" without PTT.

Age each existing idea one tier if unactioned. Archive any that hit `cold`. Pinned ideas don't age.

### Phase 5 — Request backlog triage

- **REQ-001** (planned, dimension 5): no changes on main, kickoff doc at `knowledge/handoffs/2026-04-22-meeting.md` still valid. Keep `planned`, refresh notes with today's Meeting Mode sub-score. If a `hot` upstream unlocks diarization, move to `planned` with link.
- **REQ-002** (integrated-awaiting-verify, dimensions 2+4+5): 0/7 verify boxes unchanged for 2 days. If age ≥ 48 h without verification AND still uncommitted, downgrade to a new BACKLOG-DEBT call-out in the report and flag in `LEARNINGS.md` under the existing WATCH entry as a 2nd occurrence (the 2nd occurrence of the "massive capability landing sits uncommitted" pattern — promotable to rubric).

No new `--ask` this invocation, so no new entries.

### Phase 6 — Report + persist

Write to stdout using the Report Format block in SKILL.md, then persist:
1. `MASTER_SCORECARD.md` — new scores, today's date, trend arrows vs 2026-04-23.
2. `LEARNINGS.md` — append 2026-04-24 block. Entries: (a) 2nd occurrence of uncommitted-slab pattern → propose promotion to `SCORING_RUBRIC.md` next run; (b) per-persona tool grants + prompt library landed; (c) any new patterns surfaced during Phase 2 grading.
3. `INTEGRATION_IDEAS.md` — age transitions, new II entries from Phase 4, upstream pickups from Phase 3.
4. `REQUESTS_LOG.md` — refresh REQ-001 and REQ-002 state notes with 2026-04-24 timestamp.
5. `history/2026-04-24-audit.md` — full snapshot (copy the scorecard block + scores + counts + delta vs 2026-04-23 for future diffing).

## Critical files (read-only for this run)

- `c:/code/zero/.claude/skills/zero-reachy-audit/SKILL.md` (playbook)
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/SCORING_RUBRIC.md` (grading formulas)
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/CAPABILITIES_MAP.md` (prior inventory baseline)
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/MASTER_SCORECARD.md` (prior scores)
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/LEARNINGS.md`
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/INTEGRATION_IDEAS.md`
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/REQUESTS_LOG.md`
- `c:/code/zero/.claude/skills/zero-reachy-audit/knowledge/history/2026-04-23-audit.md` (baseline snapshot)
- `C:/code/reachy-apps/HARVEST_MANIFEST.md` (wave completion check)

## Files written (persist-only, no other edits)

- `knowledge/MASTER_SCORECARD.md` (rewrite)
- `knowledge/CAPABILITIES_MAP.md` (rewrite from Phase 1 output)
- `knowledge/LEARNINGS.md` (append 2026-04-24 block)
- `knowledge/INTEGRATION_IDEAS.md` (age + new ideas + upstream pickups)
- `knowledge/REQUESTS_LOG.md` (refresh REQ-001, REQ-002 timestamps + notes)
- `knowledge/history/2026-04-24-audit.md` (new snapshot)
- `knowledge/history/hf_spaces_2026-04-24.json` (new cache)
- `knowledge/history/pollen_repos_2026-04-24.json` (new cache)

## Safety constraints (from SKILL.md)

- **No daemon restart.** Read-only on port 8000.
- **No modifications to `reachy_service.py` or any Reachy code.** Audit reads source; any fix is a separate session.
- **No deletions/renames in `C:\code\reachy-apps\`.** Reference mirror.
- **One HF Spaces + one Pollen API call max.**
- **No new scheduler jobs** — if Phase 4 suggests one, file it as an II instead.
- **Conservative grading.** 100 requires full coverage + zero quality deductions + all upstream waves integrated + full observability. Most dimensions should stay in B–A range.

## Verification

A successful audit satisfies the "Exit Criteria" from SKILL.md:
- [ ] `MASTER_SCORECARD.md` timestamped 2026-04-24
- [ ] `history/2026-04-24-audit.md` created
- [ ] `LEARNINGS.md` has ≥ 1 new entry dated 2026-04-24
- [ ] Every `pending` or `researched` REQ either triaged or explicitly skipped with reason
- [ ] Report printed to stdout in the Report Format block
- [ ] Any dimension regressed 5+ points → `REGRESSIONS` section explains why
- [ ] `history/` caches for HF Spaces + Pollen repos created

End-to-end sanity check after persistence:
1. `git status --short .claude/skills/zero-reachy-audit/` shows all 5 knowledge files modified + 3 new `history/` files.
2. `MASTER_SCORECARD.md` diff shows new timestamp and at least one trend arrow movement.
3. `LEARNINGS.md` diff shows 2026-04-24 section header.
4. Reading `INTEGRATION_IDEAS.md` top-down, the `hot` list still fits on a page (≤ ~12 items) — ideas aged correctly.
