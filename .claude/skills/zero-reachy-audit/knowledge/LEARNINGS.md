# Reachy Audit Learnings

Pattern log. Each entry: date, dimension, symptom, hypothesis, status (`[WATCH]` / `[PROMOTED]` / `[DEMOTED]` / `[RESOLVED]`). Promoted patterns migrate to SCORING_RUBRIC.md as checkable rules on the next audit. Demoted patterns get flagged for architectural review.

## 2026-04-24 — Strict-rubric audit + 2nd occurrence of uncommitted-slab pattern

### [PROMOTED-CANDIDATE] Massive capability landing sits uncommitted — now 2 audits old
- **Dimension**: cross-cutting (deploy)
- **Prior occurrence**: 2026-04-23 `[WATCH]` entry — 14 new files / 2.5k+ LOC uncommitted.
- **This occurrence**: **2nd consecutive audit** with the same slab **still uncommitted** AND growing. Today's inventory counts 28+ new files / 20+ modified files (realtime voice, REQ-002, host_agent supervisor + wake loop + live transcription, `reachy_profiles/` 16-persona data dir, `reachy_prompts_library/`, persona intros + user memory services). Not one of them has landed on `main`. Last Reachy commit on main is `b05af9a` (knowledge seed). Last feature commit is `8d28e24` (UI coverage). Commit Debt = 2 audits.
- **Hypothesis**: This is now a **structural** pattern, not a one-off. The build-then-commit rhythm has broken. A hardware failure at this moment would lose: OpenAI Realtime + Gemini Live streaming voice, REQ-002 (meeting prep + email voice triage), host_agent mic/wake/transcription stack, 16-persona data directory, composable prompt library, migration 038.
- **Audit impact**: This pattern is now load-bearing for scoring. Voice (−7) and Presence (−10) dinged partly because adding new capability without landing it counts against Freshness and Quality (more excepts accumulate without a checkpoint).
- **Proposed promotion for SCORING_RUBRIC.md**: "**Commit Debt deduction** — if any working-tree-only capability spans 2+ consecutive audits without landing on `main`, apply a −5 to each dimension that capability touches, until landed. Resets on first commit." Add to the Freshness sub-metric.
- **Status**: **[PROMOTED-CANDIDATE]**. If a 3rd audit sees the same slab uncommitted, auto-apply the rule. Until then, documented here and applied informally this run.

### [RESOLVED] Bare `datetime.now()` swept across Reachy surface (fixed 2026-04-24 post-audit)
- **Dimension**: Presence & Ambient + Meeting Mode + Environment & Integrations
- **Symptom**: Phase 1 inventory flagged 1 bare `datetime.now()` in `reachy_presence_service.py`. Post-audit sweep found **5 total** across 3 Reachy-scoped files:
  - `reachy_presence_service.py:325` (comparison site in hourly chime)
  - `reachy_context_service.py:65, 229` (prompt-block time display)
  - `meeting_recording_service.py:161, 172` (title + filename timestamp formatters)
- **Fix**: Replaced each with `datetime.now(timezone.utc).astimezone()`. Keeps local-time display semantics while making the call tz-aware so comparisons against aware datetimes never raise `TypeError`. `timezone` already imported in all three files.
- **Rubric impact**: Recovers the −10 quality deduction on Presence. Next audit should see Presence quality → ~90 (from 60), pushing the dimension back to A range.
- **Status**: `[RESOLVED]`. If a new bare call appears in a 3rd+ cycle, promote a rubric rule: "every file touching time must use `datetime.now(timezone.utc).astimezone()` for local-time needs".

### [RESOLVED] Silent `except Exception: pass` in realtime voice commit/cancel paths (fixed 2026-04-24 post-audit)
- **Dimension**: Voice & Conversation
- **Symptom**: `reachy_realtime/openai_handler.py` had two `except Exception: pass` blocks around `commit_audio()` and `cancel_response()` — failures vanished without logs. Three other `except Exception: pass` blocks in cleanup/shutdown paths (openai_handler stop, session _cleanup, gemini_handler stop) are defensible — idempotent shutdown ops.
- **Fix**: Added `logger.debug("openai_commit_audio_dropped", error=str(e))` and `logger.debug("openai_cancel_response_dropped", error=str(e))` to match the existing `openai_feed_pcm_dropped` pattern at line 207. 3 cleanup-path blocks left as-is.
- **Rubric impact**: Doesn't change the raw except-count deduction (rubric counts `except Exception:`, not "silent" vs "logged"). But feeds the `[WATCH]` entry below on rubric calibration — when we eventually promote "silent swallows deduct extra, logged-and-recovered blocks are free," these lines are already on the right side.

### [WATCH] Growing `except Exception:` count in long-running services
- **Dimension**: Voice & Conversation + Presence & Ambient
- **Symptom**: `voice_loop_service.py` now has **14** `except Exception:` blocks (vs ~4 when the rubric was first applied). `reachy_presence_service.py` has **10**. The realtime package adds another **33** across 11 files (openai_handler 9, gemini_handler 9, session 7, head_wobbler 3, bg_tool_manager 2, tools 3, profiles 1, config_store 1). Both files hit the −30 quality cap.
- **Hypothesis**: Both services are long-running async loops with many external boundaries (daemon REST, LLM, TTS, STT, scheduler, WS). Every new integration adds another `except Exception:` to isolate that boundary from the loop. The pattern is **structurally correct** — a voice loop really does need to not crash on any transient external failure — but the rubric treats it as a pure deduction.
- **Tension**: Rubric rewards code without broad error handling; product requires code with broad error handling in the voice + presence loops. These goals disagree.
- **Proposed refinement for SCORING_RUBRIC.md** (not yet promoted): Carve out "long-running async service" exceptions: count only `except Exception:` blocks that (a) swallow silently without logging, or (b) have no `raise` / no structlog call inside. Blocks that log + dispatch to a watchdog counter should be free.
- **Status**: `[WATCH]`. This is a rubric-calibration issue, not a code issue. Flag for thinking, not fixing.

### [WATCH] Verification Debt is different from Backlog Debt
- **Dimension**: Meeting Mode (REQ-002 specifically)
- **Symptom**: REQ-002 has been `integrated-awaiting-verify` for **48 h with 0/7 verification boxes checked**. `Backlog Debt` per rubric stays 0 (the request isn't `pending`). But there is real debt — shipped code that no one has confirmed works on the physical robot.
- **Hypothesis**: The state machine in `REQUESTS_LOG.md` has a dead-air zone between `integrated` and `verified`. Without a deadline or nudge on verification, code accumulates in limbo: coded, working in theory, never actually tried.
- **Proposed refinement for SCORING_RUBRIC.md**: add a **Verification Debt** cross-cutting metric = count of requests in `integrated` state older than 48 h. Surfaces alongside Backlog Debt in every report. A request that sits unverified for 7 d should auto-downgrade to `researched` and trigger a re-plan (maybe the approach was wrong).
- **Status**: `[WATCH]`. Tracked informally in the scorecard this run as "Verification Debt: 1" but not yet promoted to a gradable deduction.

### [RESOLVED] host_agent venv issue (from 2026-04-22)
- **Dimension**: Infrastructure Health
- **Status**: Still resolved. `.venv` present, supervisor running.

### [WATCH, ongoing] Gesture-fires-after-TTS (from 2026-04-22)
- Still unverified. No measurement this run.

### [WATCH, ongoing] UP-001 streaming voice shipped without idea state transition (from 2026-04-23)
- Still unresolved — idea auto-archived by the audit retcon system. If a 2nd idea skips its state transitions, add `--archive-if-shipped` automation.

## 2026-04-23 — Realtime voice + sequences + REQ-002 snapshot

### [WATCH] Massive capability landing sits uncommitted on working tree
- **Dimension**: cross-cutting (deploy)
- **Symptom**: Audit found ~14 new files / 2,500+ LOC for OpenAI Realtime + Gemini Live (`reachy_realtime/`), `reachy_sequence_service`, `voice_intent_router`, `email_voice_session_service`, `meeting_auto_recorder_service`, `voice_bridge_service`, `reachy_chat_provider`, plus migration `038_reachy_sequences.py` and two new test files — **all still in working-tree `M` / `??` state**. None on `main`.
- **Hypothesis**: Build-then-commit rhythm is slipping. Every audit cycle between commits is one disk-failure away from losing a whole capability wave.
- **Mitigation**: Flag in the report as TOP next-step. Treat a completed wave (realtime, sequences, REQ-002) as a "must-commit-before-sleep" trigger.
- **Status**: WATCH. **Now 2nd occurrence at 2026-04-24** — see PROMOTED-CANDIDATE entry above.

### [RESOLVED] host_agent venv issue flagged YELLOW last audit
- **Status**: RESOLVED. Infra GREEN.

### [WATCH] UP-001 streaming voice shipped in-tree before any prior idea state transition
- **Status**: WATCH (see 2026-04-24 follow-up above).

### [WATCH] Meeting mode verification still unverified on physical robot
- **Status**: **2 days in and still 0/7**. Escalated via new **Verification Debt** metric (2026-04-24).

## 2026-04-22 — REQ-002 build (meeting prep + email voice triage)

### [WATCH] One-shot voice loop assumption blocks multi-turn flows
- **Dimension**: Voice & Conversation
- **Symptom**: The pre-existing `voice_loop_service.process_voice_input` was strictly stateless: every call was transcribe → LLM → speak → return. Building the email triage state machine required a parallel control path because the loop had no notion of "continue an existing conversation".
- **Status**: WATCH. 3rd-flow trigger not yet seen.

### [WATCH] gmail.modify scope is broader than the name suggests
- **Status**: WATCH (informational).

### [WATCH] Reader voice pinned to edge-tts only
- **Status**: WATCH.

## 2026-04-22 — Seed run (from harvest session)

### [RESOLVED] Daemon dataset path needs org prefix
- **Commit**: `caf89be`. **Status**: RESOLVED.

### [RESOLVED] Voice-loop LLM fallback called non-existent router method
- **Commit**: `9a01e35`. **Status**: RESOLVED.

### [WATCH] Desktop app crashes on lazy dataset download
- **Mitigation**: Headless launcher. **Status**: WATCH (no regression since mitigation).

### [WATCH] MediaPipe wheel lacks `mp.solutions` on some indexes
- **Status**: WATCH.

### [WATCH] Routes shadowed by dynamic path parameters
- **Status**: WATCH. Re-verify with this run's 89-route expansion next audit.

### [WATCH] Rebuild misses in-flight edits
- **Status**: WATCH.

### [WATCH] Gesture dispatched after TTS finishes
- **Status**: WATCH (unmeasured).

## Seeded anti-patterns (from SKILL.md)

| Anti-pattern | Dimension | Detection | Fix direction | Status |
|---|---|---|---|---|
| Wake word off-thread blocks main loop | Voice | `wake_loop.py` CPU > 50% single-core | Move to subprocess w/ ring buffer | [WATCH] — `host_agent/wake_loop.py` + `whisper_wake_loop.py` exist; not measured |
| DoA angle drifts when antennas move | Meeting | DoA reading + antenna position correlated | Require daemon ≥ 1.6.4 | [WATCH] — on 1.6.4 |
| Presence beat runs while daemon offline | Presence | 404s from daemon on every beat | Gate with `is_connected()` before dispatch | [WATCH] — mitigation in place |
| HA watcher eats API quota | Environment | Poll interval too aggressive | Respect `ZERO_HA_POLL_SECONDS`, back off on 429 | [WATCH] |
| Motion library clip plays but aliasing fails | Motion | LLM emits `[emotion:happy]`, daemon 404 | Alias resolver fallback chain | [RESOLVED] |

## Additions this run (inventory delta vs 2026-04-23)

Files observed for the first time in this audit (no prior CAPABILITIES_MAP row):
- `backend/app/services/reachy_persona_intros_service.py`
- `backend/app/services/reachy_user_memory_service.py`
- `backend/app/data/reachy_profiles/` (16 persona subdirs, each with `instructions.txt` + `tools.txt`; `example/` has `sweep_look.py`)
- `backend/app/data/reachy_prompts_library/` (`identities/`, `behaviors/`, `default_prompt.txt`, `passion_for_lobster_jokes.txt`)
- `host_agent/supervisor.py`, `supervisor_only.py`, `wake_loop.py`, `whisper_wake_loop.py`, `audio_capture.py`, `voice_capture.py`, `camera_worker.py`, `live_transcription.py`, `audio_buffer.py`, `check_threads.py`, `probe_mic.py`, `probe_callback.py`, `main.py`
- `frontend/src/components/reachy/ReachyCameraViewer.tsx` (new camera viewport component)

Files present at 2026-04-23 but removed now: **none**. Zero regressions.

## How to use this file

When the audit hits a symptom, look here first. If it matches:
- `[WATCH]` — log a new occurrence below the entry. After 2 occurrences with a reliable fix, promote.
- `[PROMOTED-CANDIDATE]` — 2 occurrences seen, promotion proposed. If a 3rd occurrence happens, auto-promote to `SCORING_RUBRIC.md`.
- `[PROMOTED]` — rule is in the rubric; this entry is historical.
- `[DEMOTED]` — fix failed repeatedly; flag for arch review, stop auto-applying.
- `[RESOLVED]` — historical record, no new occurrences expected.
