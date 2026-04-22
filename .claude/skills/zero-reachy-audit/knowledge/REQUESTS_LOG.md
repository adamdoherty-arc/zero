# Reachy Capability Requests Log

User-filed "I want Reachy to do X" items. Each entry has a lifecycle: `pending` → `researched` → `planned` → `integrated` → `verified`. Archive rows move to `history/requests_archive.md` after 30 days in `verified`.

## Open requests

### REQ-001: Deep-dive the Meeting Mode dimension
- **Filed**: 2026-04-22
- **Raw ask**: "I want to focus next on meetings, but I want to run that from a fresh prompt."
- **State**: `planned`
- **Dimension guess**: 5 (Meeting Mode)
- **Current score**: C+ (78/100). Biggest sub-score deficit: coverage (65).
- **Minimum delta**: see `handoffs/2026-04-22-meeting.md` — three priority gaps identified (speaker diarization, nod-on-highlight, persona-aware meeting).
- **Blocker**: none — all prerequisite capabilities (DoA loop, persona swap, meeting recording pipeline) are already shipped.
- **Fresh-prompt kickoff**: paste the block from `handoffs/2026-04-22-meeting.md` into a new Zero session.
- **Linked ideas**: II-002 (meeting-mode persona swap), II-003 (nod on highlight), UP-005 (mediapipe migration — if meeting vision lands).
- **Notes**: User confirmed this is the highest-priority capability investment as of 2026-04-22.

## Archived / verified

_(none yet — first audit.)_

## Lifecycle guide

| State | Meaning | Transition rule |
|-------|---------|-----------------|
| `pending` | Filed but not yet analyzed | Next audit triages, maps to a dimension, links upstream |
| `researched` | Triaged; upstream + dependencies identified | Promotes when a code plan exists |
| `planned` | Has a handoff doc or execution plan | User/claude action begins |
| `integrated` | Code on `main`, smoke tests pass | Awaits verification on physical robot |
| `verified` | Live-tested, committed, no regressions | Archive after 30 days |

A request stuck in `pending` for >14 days triggers a nudge in the audit report (Backlog Debt metric).

## How to file a new request

```
/zero-reachy-audit --ask "I want Reachy to <thing>"
```

The skill will:
1. Append a `pending` entry here with a triage stub.
2. Map it to a dimension.
3. Scan upstream for anything that unlocks it (Phase 3).
4. Identify the minimum code delta.
5. Propose the next state (`researched` or `planned`).

It will **not** write any code — that's a separate session. This log is a backlog, not an executor.
