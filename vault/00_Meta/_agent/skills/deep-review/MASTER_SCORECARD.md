# Zero — Deep Review Master Scorecard

## Run 2026-07-01 — "Baseline to 100%" (zero-studio-pollen, branch feat/zero-world-class-agent)

### Persona grades

| Persona | Pre-fix | Post-fix | Movement drivers |
|---|---|---|---|
| Conversational robot | A- (92) | **A (95)** | Semantic EOT v2 (false-hold fix on particle commands, whisper-period handling); local Kokoro TTS option (cloud dependency removable); silero-vad option; +14 music dances |
| Personal assistant | B+ (85) | **A- (91)** | Meetings→tasks auto-convert ON by default + UI toggle; approvals error surfacing fixed (silent draft-save failure was dangerous); daemon-wait tuning ends warm-relaunch COM3 collisions |
| Second brain | B (80) | **A- (90)** | Embedder straggler sweep (hash-v1 blip facts no longer permanently invisible); ZERO_MEMORY_SELFTEST proves recall→LLM injection E2E via the real shared path; learned-rules management UI |

### Feature wiring (audit of all 21 nav surfaces)

All 21 surfaces FULL-wired; 0 broken invoke() calls (129/129 registered). 13 legacy
v1 registrations pruned (fns retained for agent tools + selftests). Audit false
positives caught by verify-first: motion.rs "duplication" (it's the live 50 Hz
engine), update/mod.rs "inert" (live daemon updater), approvals "dark" (fully
wired in Today), voice-enrollment "missing" (SettingsVoiceRecognitionCard exists),
7 "orphan" db_meeting_*/brief commands (live in meetings CRUD + Today).

### Commits this run (13)

568e28a daemon-wait tuning · e29b27b F12 closed (docs) · a6c5f20 EOT v2 ·
8569bc4 embed straggler sweep · 76650ff ZERO_MEMORY_SELFTEST · bfe7d7e voice-engine env plumbing ·
b1160ac legacy prune · 9991938 trampoline setpgid (upstream) · 7aedf3c music dances (upstream) ·
bde753e catalog Age header (upstream) · dd062b7 Kokoro TTS · 676dc95 silero-vad ·
65addf1/58d2ad8/778fdee/4ed638f frontend P1 pack (TS type fixes incl. latent scan-effect crash,
meetings toggle, approvals error surfacing, learned-rules card)

### Gates

cargo test --lib 654/654 · vitest 781/781 (47 files) · tsc clean · zero_voice pytest 152/152.

### Growth backlog (parked, prioritized)

1. Closing-view real shutdown progress (upstream 1370f88 — conflicted, reimplement narrowly)
2. Speech-reactive wobble parity check vs Pollen conversation app v0.8.0 (we have speech sway; verify amplitude/beat-gesture parity)
3. mem0/Graphiti-style memory consolidation patterns (temporal facts, profile merge visibility)
4. Next-task suggestion; email→calendar auto-block; journaling UI; long-term trend detection
5. Multi-speaker owner-priority; antenna-mood TTL extension
6. Signed installer (F15); legacy-repo retirement (F16)
7. Orphan phase-2 exposures (nf_*/activity_* admin surfaces)
8. Kokoro/silero flip to DEFAULT after operator A/B approves (currently opt-in via ZERO_VOICE_TTS_ENGINE/VAD_ENGINE)
