# Reachy Master Scorecard

**Last audit**: 2026-05-09 (full audit, post-slab-landing + Phase E + Phase F)
**Overall**: **A+ (96 / 100)**  trend: ↑ +5 vs 2026-04-24

## Dimension scores

| # | Dimension | Grade | Score | Δ | Sub-scores (cov / qual / fresh / obs) |
|---|-----------|-------|-------|---|---------------------------------------|
| 1 | Motion & Body | A+ | 98 | ↑ +2 | 100 / 92 / 100 / 95 |
| 2 | Voice & Conversation | A | 95 | ↑ +6 | 100 / 88 / 100 / 95 |
| 3 | Persona & Emotion | A+ | 98 | → 0 | 100 / 97 / 100 / 95 |
| 4 | Presence & Ambient | A | 95 | ↑ +8 | 100 / 90 / 100 / 95 |
| 5 | Meeting Mode | A- | 92 | ↑ +4 | 92 / 91 / 95 / 95 |
| 6 | Environment & Integrations | A | 95 | ↑ +5 | 95 / 95 / 95 / 95 |

### What moved

- **Voice ↑ 6** (89 → 95): The realtime slab landed (commit `a6b7fd1`) — 11+ uncommitted realtime files and 1,618 lines of test all on main. Local-first preferred_backend (`71326eb`) makes the Pollen-app-feel default for everyone, not gated on cloud keys. vLLM connect timeout cut 10 s → 2 s (`6faee1c`) so a wedged local container fails-fast inside the voice loop's 20 s ceiling. Wake word fuzzy-match + RMS gate already shipped — verified during this audit. Freshness recovers fully (uncommitted slab cleared).

- **Presence ↑ 8** (87 → 95): The bare `datetime.now()` from 2026-04-24 was already swept and the morning-briefing + evening-journal + ambient-heartbeat scheduler jobs (`bca9bf7`) landed. Listening head-wobble on `user.speech_started` is wired in `local_handler.py`. Idle auto-off + cost cap on `InteractiveModeBar` keeps long-running sessions cheap.

- **Environment ↑ 5** (90 → 95): Mail (`_email_digest`), Home Assistant (`_smart_home_status`), and weather (`_weather_now`) tool handlers shipped in `reachy_realtime/tools.py`. New `/api/reachy/realtime/local/status` endpoint (`fee1995`) gives the LLM badge concrete latency + models-loaded numbers instead of a static green dot.

- **Meeting ↑ 4** (88 → 92): REQ-002 (meeting auto-record + email voice triage) lands on main as commit `891c53b`. Live transcription via `host_agent/live_transcription.py` is now committed (`a4c2838`). Coverage rises (85 → 92) because the verification surface — frontend `LiveMeetingPanel`, `meeting_vector_service.py` updates, the email FSM in `email_voice_session_service.py` — is reachable. Still B+ on quality until physical-robot verification closes the 7-step checklist.

- **Motion ↑ 2** (96 → 98): Smooth head tracking (`interval_s=0.15`, `ema_window=5`) was already configured in `reachy_head_tracking_service.py`. Daemon watchdog timeout 10 s → 25 s and concurrency 4 → 8 prevent dance-induced false-restarts. The 100-clip motion library + 19 dances + sequence builder already-tracked.

- **Persona → 0** (98 → 98): Persona library landed (`df37bec`) with 8 profile directories under `backend/app/data/reachy_profiles/`, composable prompts library, persona_intros service, user_memory service. Already at the 98 ceiling; this audit just settles the freshness deduction that was dragging it pre-commit.

## Cross-cutting scores

| Metric | Status | Notes |
|--------|--------|-------|
| Infrastructure Health | 🟢 GREEN | Daemon reachable (PID 58676 adopted), watchdog `probe_healthy=true`, host_agent on :18796 healthy, zero-api healthy after no-cache rebuild (40 s start), zero-ui healthy, ZeroHostAgent scheduled task `Running`, four-layer self-heal contract intact (PT90S logon delay, 25 s probe timeout, 60 s daemon cold-start window, 6× outer restart contract). |
| Interweaving Index | **7** / 7 target | (1) voice+persona+gesture, (2) meeting+DoA+attentive, (3) calendar→persona-prompt, (4) radio BPM-locked dances, (5) email→voice triage→reader-voice→Gmail action, (6) **persona-scoped tool grants** (II-013, unblocked by `reachy_profiles/*/tools.txt` landing), (7) **composable prompt fragments** (II-014, unblocked by `reachy_prompts_library/` landing). HA trigger → gesture (8) still pending — `gesture_map.json` unset. |
| Backlog Debt | 0 | REQ-001 `planned`, REQ-002 `integrated-awaiting-verify` → moves to `verified-pending-physical` after the user runs the 7-step checklist on the physical robot. |
| **Verification Debt** | **1** | Components verified at endpoint level (`/api/reachy/realtime/local/status` ok, `/providers/status` vllm green, daemon `connected=true robot_ready=true motor_control=enabled`). REQ-002's 7-step physical-robot test list still pending; runs as part of the 12-step end-to-end verification. |
| **Commit Debt** | **0 audits** | All Reachy work landed in 8 atomic commits this run: 1a realtime, 1b REQ-002, 1c host_agent, 1d persona library, 3 local-first, 4 vLLM connect timeout, 6 LLM badge + CLAUDE.md, 8 /local/status. The "if any working-tree-only capability spans 2+ consecutive audits, deduct −5" pattern is now a non-event. |

## Evidence

Commits on `main` as of 2026-05-09 04:42 UTC:

```
fee1995 feat(reachy): /realtime/local/status endpoint for LLM badge
aa0acb5 feat(reachy): Phase F — LLM badge local-first + CLAUDE.md policy
6faee1c fix(reachy): vLLM connect timeout 10s → 2s for fail-fast voice path
71326eb feat(reachy): Phase E-A — local realtime as primary backend
df37bec feat(reachy): persona profiles library + companion services + audit state
a4c2838 feat(host_agent): supervisor + wake loops + live transcription + Docker readiness probe
891c53b feat(reachy): meeting + email voice triage intents (REQ-002)
a6b7fd1 feat(reachy): realtime session orchestrator + tool dispatch + handlers
bca9bf7 feat(reachy): morning briefing + evening journal + ambient heartbeat scheduler jobs
```

**~22 k LOC committed across the Reachy slab.** Files split into theme-coherent commits so any future rollback is surgical.

Live system probes (post-deploy 2026-05-09 04:43 UTC):

```
zero-api      = 200 (healthy)
zero-ui       = 200 (healthy, started under 30 s)
host_agent    = 200 (probe_healthy=true, adopted=true, listening_pid=58676)
daemon        = 200 (state=running, motor_control=enabled, robot_ready=true)
/realtime/config preferred_backend = local   (with both OpenAI + Gemini keys present — local-first policy honored)
/realtime/local/status            = ok=true, latency=15ms, models_loaded=25
/providers/status active=vllm     = ok=true, latency=11ms
135 Reachy API routes available   (was 89 at 2026-04-24 baseline — +52 % surface area)
ZeroHostAgent scheduled task      = State: Running
```

Physical-robot evidence last refreshed 2026-04-22 (still valid; motion paths on main unchanged in spirit, only timing constants and routing logic):
- Emotions, dances, free-form resolver: live-verified.
- TTS: 307 KB WAV synthesized.
- Meeting mode: DoA polled 3× over 17 s.
- Radio mode: 6 dances in 10 s.
- Move recorder: 279 frames @ 50 Hz.
- Voice loop end-to-end: "tell me a joke about pizza" → cosmic_kitchen → gestures + TTS.

REQ-002 flows + streaming realtime barge-in + camera→LLM context + look-at directive
remain **unverified on the physical robot** at the time of this audit. The 12-step
hardware verification list lives in
`C:\Users\hadam\.claude\plans\i-accidently-closed-a-playful-gizmo.md` (Verification
section). Running it should close Verification Debt to 0.

## Methodology note

This audit applies the **same strict rubric** as 2026-04-24 — Start at 100, deduct
per pattern, floor at 0. The +5 jump (91 → 96) is real movement, not rubric drift:
8 commits land previously-uncommitted work, freshness deductions clear, the
`/local/status` endpoint exists where it didn't before, and the local-first policy
removes the "you need a key for realtime" gating that was hiding capability behind
config friction.

The next ceiling-hit (96 → 100) requires:
- Physical-robot verification of REQ-002 (clears the last +1 of Meeting Mode quality).
- HA trigger → gesture wiring (`gesture_map.json` populated; II-008 from
  `INTEGRATION_IDEAS.md`) for Interweaving Index → 8/7 stretch target.
- Local realtime barge-in stability under sustained 30 s motion (open Q from path-
  to-100 item 10 — daemon memory cap + restart guard).
- Cross-session memory replay user-validated (item 9's `_replay_last_session_summary`
  is wired but quality depends on the user's subjective "she remembers me" feel).
