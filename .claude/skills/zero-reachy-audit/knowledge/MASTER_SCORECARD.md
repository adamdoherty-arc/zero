# Reachy Master Scorecard

**Last audit**: 2026-04-22 (seed run, no trend data yet — arrows will populate on the next audit)
**Overall**: **A- (91 / 100)**  trend: —

## Dimension scores

| # | Dimension | Grade | Score | Δ | Sub-scores (cov / qual / fresh / obs) |
|---|-----------|-------|-------|---|---------------------------------------|
| 1 | Motion & Body | A- | 92 | — | 95 / 90 / 100 / 90 |
| 2 | Voice & Conversation | B+ | 87 | — | 88 / 85 / 85 / 95 |
| 3 | Persona & Emotion | A | 95 | — | 95 / 92 / 100 / 95 |
| 4 | Presence & Ambient | A- | 92 | — | 90 / 95 / 95 / 92 |
| 5 | **Meeting Mode** | **C+** | **78** | — | 65 / 90 / 90 / 95 |
| 6 | Environment & Integrations | B+ | 88 | — | 85 / 88 / 95 / 88 |

Meeting Mode is the headline gap — functional but scoped. Coverage of the target surface (`SCORING_RUBRIC.md` dim 5) is 7/11: missing speaker diarization, nod-on-highlight, persona-aware modes, and Reachy-mic audio capture integration. This is the user's chosen next focus.

## Cross-cutting scores

| Metric | Status | Notes |
|--------|--------|-------|
| Infrastructure Health | 🟡 YELLOW | Daemon reachable ✅ · host_agent venv ⚠ not yet installed · USB audio ✅ bound · Port 8000 ✅ clear |
| Interweaving Index | **3** / 5 target | Working: voice loop + persona + gestures (2+3); meeting mode + DoA + attentive (1+5); calendar context → prompt (3+6). Stretch (not wired): HA trigger → gesture (4+6), BPM radio → beat-locked dances (1+external audio — works but isolated). |
| Backlog Debt | 0 | No `pending` requests yet — this is a seed run. |

## Evidence for this scorecard

Based on commits on `main` 2026-04-22:

```
8d28e24 UI coverage: 61 routes → 40 hooks → 3 pages
9a01e35 Voice loop LLM fallback (unified_llm_client)
caf89be Dataset prefix fix (pollen-robotics/ org)
7c13972 Waves 10-17
ddf20b6 Waves 3/6/7/8 completion
47c8571 Waves 3/6/7 initial
10c319c Wave 8 installable app
f5f99d7 Wave 4 meeting mode
82e7572 Wave 5 ambient scheduler
a21b9d0 Wave 2 personas
dafa41b Wave 1 motion library
```

Plus headless daemon launcher (`host_agent/run_reachy_daemon.bat`) and 25/25 smoke tests passing.

Live-verified on physical Reachy:
- Emotions (happy, surprised1, laughing1) played
- Dances (simple_nod, dizzy_spin, yeah_nod) played
- Free-form resolver ("i did it" → proud3) worked
- TTS 307 KB WAV synthesized + spoken
- Meeting mode DoA polled 3× over 17 s
- Radio mode dispatched 6 dances in 10 s
- Move recorder captured 279 frames @ 50 Hz, saved, replayable
- Voice loop end-to-end: "tell me a joke about pizza" → cosmic_kitchen persona → `[emotion:happy] [dance:yeah_nod] Why did the pizza go to space?...` → gestures + TTS
