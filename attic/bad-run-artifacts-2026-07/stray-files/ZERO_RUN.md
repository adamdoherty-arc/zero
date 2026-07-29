# Zero Run 15a0e158-4fa9-4d8f-9d8b-80df37495b92
Date: 2026-05-22 · Robot state at close: live · DND: off

## Pre-flight

| Check | Status |
|---|---|
| run_id captured | ✓ 15a0e158-4fa9-4d8f-9d8b-80df37495b92 |
| Reachy daemon | reachable (HTTP 200 at :8000) |
| host_agent | reachable (HTTP 200 at :18796) |
| DND | off |
| Bifrost | UNREACHABLE at start, FIXED (probe was using port 4445 not 8080) |
| Langfuse | unreachable (zero-langfuse-web DNS not resolving; not in sprint stack) |
| approvals.open | -1 (API error; likely DB query issue) |
| cyanheads_obsidian MCP | false — Stage-2 vault writes blocked (Obsidian plugin not running) |
| legion_mcp | false (not wired in this session) |
| ada_mcp | false (not wired in this session) |
| vault constitution | agent_writable respected; no vault writes this run |
| approval tier | write_local (code edits only, no external writes) |
| OAuth presence | not claimed this run |
| Voice loop billing | no session started; FloatingVoiceButton not touched |

## Delegations dispatched

| target | id | sprint/signal | status |
|---|---|---|---|
| (legion_mcp unavailable — code fixes executed directly) | — | — | — |

## Vault writes

None this run.

## Approval records created

None — all changes were write_local code edits, no external writes triggered.

## Sprints (write-through to Legion :8005 project_id=7)

| legion_sprint_id | slug | size | subsystem | robot-off-safe | status |
|---|---|---|---|---|---|
| 5636 | Audit-55 | S (3pts) | biometric auth | yes | completed |
| 5634 | Audit-54 | S (3pts) | Stage-2 MCP readiness | yes | completed |
| 5632 | Audit-52 | XS (1pt) | stack-facts probe | yes | completed |

### Sprint details

**Audit-55** — `voiceprints.py` and `faceprints.py` had `router = APIRouter()` with no auth. Any actor at `:18792` could enroll, list, or delete biometric identities. `enroll-path` accepted arbitrary filesystem paths with no workspace constraint (path traversal). Fixed: added `dependencies=[Depends(require_auth)]` to both routers; added `get_workspace_path("meetings")` path allowlist to `enroll-path`.

**Audit-52** — `zero_run.py` Bifrost probe defaulted to `http://shared-bifrost:4445` (host-mapped). Inside Docker the correct internal address is port 8080. Changed default; Bifrost now shows `reachable` in stack-facts.

**Audit-54** — Stage-2 cyanheads-obsidian MCP was silently blocked with no diagnostic. Added `GET /api/zero/stage2/readiness` endpoint (checks OBSIDIAN_API_KEY, probes `:27124`, verifies MCP presence). Added `docs/stage2-mcp-setup.md`. Stage-2 remains blocked until Adam installs the Obsidian Local REST API plugin and sets OBSIDIAN_API_KEY.

## Gaps surfaced (Phase 4)

Adversarial subagent running; new Audit-* sprints being filed under `source_system=zero-supervise-adv`. Check Legion after 2026-05-22T19:52 for new entries.

Previously active (filed prior run, unexecuted):
- Fix-11: camera capture starts without consent re-check (host_agent, M)
- Fix-12: voiceprint match runs on private meetings without consent gate (M)
- Fix-13: consent-window state machine missing — recording not blocked after expiry (M)
- Fix-14: consent_needed events use fire-and-forget DB persist, can be lost on crash (XS)
- Fix-15: Reachy daemon motor health not validated (XS)
- Audit-57: ambient_vision_tick writes VLM captions during private meetings (S)
- Audit-59: faceprint auto-enroll + pipeline biometric leak on private meetings (M)

## Voice / robot events

No voice session started. Reachy daemon reachable throughout. No daemon transitions.

## Daily-note append

```
## Agent Summary
Zero Supervisor run 15a0e158 (2026-05-22). Shipped 3 sprints:
Audit-55 (biometric endpoints missing require_auth — SECURITY fix),
Audit-52 (Bifrost probe wrong port — now reachable),
Audit-54 (Stage-2 readiness endpoint + setup docs).
Adversarial gap subagent dispatched. Stage-2 still blocked: Obsidian
Local REST API plugin not installed/running.
<!-- agent-run-id: 15a0e158-4fa9-4d8f-9d8b-80df37495b92 source: zero at: 2026-05-22T19:52:30Z -->
```

## Next-run recommendation

1. **Fix-12 + Fix-11** (Meeting Steward consent gates, M-sized) — voiceprint match and camera capture both execute before consent is validated on private meetings. Execute next.
2. **Fix-14** (consent_needed DB persist, XS) — safety-critical events can be lost on crash.
3. **Audit-57** (ambient vision private-meeting gate, S) — cloud Gemini gets frames from private meetings.

**Run URL:** http://localhost:18792/api/zero/run/15a0e158-4fa9-4d8f-9d8b-80df37495b92
