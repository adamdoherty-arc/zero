---
name: "zero-reachy-audit"
description: "Audits the Zero ↔ Reachy Mini integration across 6 capability dimensions, grades each, checks upstream ecosystem for updates, suggests cross-dimension interweavings, and tracks user capability requests through a backlog. Has persistent ML learning across runs (scorecard history, pattern log, integration ideas, request log) so successive runs refine judgment instead of starting from scratch. Use when auditing Reachy capabilities, planning the next capability investment, or filing a new 'I want Reachy to do X' request."
version: "1.0.0"
metadata:
  zero:
    category: "robotics"
    triggers:
      - "reachy audit"
      - "reachy review"
      - "grade reachy"
      - "what can reachy do"
      - "reachy capabilities"
      - "reachy roadmap"
      - "reachy updates"
      - "reachy interweave"
      - "add to reachy"
      - "reachy request"
    requires:
      services: ["zero-api"]
      external: ["reachy-mini-daemon:8000 (optional — audit runs offline too)"]
    autonomous: false
    capabilities:
      - "6-dimension capability grading (Motion/Voice/Persona/Presence/Meeting/Environment)"
      - "Upstream ecosystem drift check (HF Spaces tag, Pollen repos, community apps)"
      - "Cross-dimension interweaving suggestions ranked by synergy"
      - "User capability-request backlog with state machine (pending → researched → planned → integrated → verified)"
      - "ML-style learning: scorecard history, pattern log, promoted fixes, demoted anti-patterns"
      - "Fresh-prompt handoff generation for deep-dives (e.g., meetings)"
---

# Zero Reachy Audit Skill

End-to-end audit of everything Reachy Mini does inside Zero. Grades capabilities, tracks upstream ecosystem updates, and maintains a persistent backlog of capability requests so every run builds on the last.

## Usage

```
/zero-reachy-audit                 # Full audit: inventory + grade + research + interweave + backlog
/zero-reachy-audit --quick         # Scorecard only (reuse last inventory, ~3 min)
/zero-reachy-audit --research      # Upstream update scan only (HF Spaces, Pollen repos)
/zero-reachy-audit --focus <dim>   # Deep-dive one dimension: motion|voice|persona|presence|meeting|environment
/zero-reachy-audit --ask "<text>"  # File a new capability request into REQUESTS_LOG.md
/zero-reachy-audit --interweave    # Only surface cross-dimension synergy ideas
/zero-reachy-audit --handoff <dim> # Generate a fresh-prompt kickoff doc for a focused follow-up chat
```

## Knowledge Files

All persistent state lives in `.Codex/skills/zero-reachy-audit/knowledge/`:

| File | Purpose | Write cadence |
|------|---------|---------------|
| `CAPABILITIES_MAP.md` | Layer-by-layer inventory of all Reachy code (services/routers/jobs/frontend/config/daemon/host_agent). Source of truth. | Full audit only |
| `SCORING_RUBRIC.md` | Dimension definitions, sub-metrics, weights, grade scale. Stable. | Manual edits only |
| `MASTER_SCORECARD.md` | Latest scores per dimension with trend arrow vs prior run. | Every audit |
| `LEARNINGS.md` | Pattern log: what blocked, what worked, what to watch. Same model as `zero-docker-health/LEARNINGS.md`. | Every audit |
| `INTEGRATION_IDEAS.md` | Candidate interweavings + upstream pickups. State machine entries. | Every audit + manual |
| `REQUESTS_LOG.md` | User-filed "add X to Reachy" requests. State-tracked to closure. | `--ask` + audit triage |
| `history/YYYY-MM-DD-audit.md` | Full audit snapshot for diffing. | Full audit only |

The audit **always** reads the prior scorecard, learnings, ideas, and requests before running — that's the ML memory loop. It must update every file it depends on, so the next run gets smarter.

## Core Concepts

### Six capability dimensions

| # | Dimension | What it measures |
|---|-----------|------------------|
| 1 | **Motion & Body** | Head/antennas/body-yaw control, emotion clips (81), dance clips (19), user-recorded moves, teleop, wake/sleep routines, motor modes |
| 2 | **Voice & Conversation** | STT → persona-wrapped LLM → TTS loop. Wake word, VAD, push-to-talk, provider switching, round-trip latency |
| 3 | **Persona & Emotion** | 12 personas, gesture-marker parsing (`[emotion:]`, `[dance:]`, `[look:]`), inline dispatch synchrony, auto-rotation, context-aware prompt hints |
| 4 | **Presence & Ambient** | Scheduler-driven ambient behaviour: pomodoro, idle watcher, hourly chime, presence beat, calendar/email voice nudges |
| 5 | **Meeting Mode** | DoA look-at-speaker, attentiveness gestures, recording-integration TTS confirmations, speaker tracking, meeting audio capture via Reachy mic |
| 6 | **Environment & Integrations** | Home Assistant bridge + watcher, gesture-map engine, vision (MediaPipe hands / face), camera stream, ecosystem app pulls from `reachy-apps/` |

Each dimension is graded across four **sub-metrics**:

| Sub-metric | Weight | What it checks |
|------------|--------|----------------|
| Coverage | 40% | What % of the target capability is implemented and reachable? |
| Quality | 25% | Code quality: error handling, structlog, tests, type safety, no TODOs |
| Freshness | 20% | Is upstream work integrated? Compare `reachy-apps/` HARVEST_MANIFEST.md against current HF Spaces tag |
| Observability | 15% | Logs, metrics, learnings — can we diagnose this dimension remotely? |

Plus three **cross-cutting scores** (not weighted, reported separately):

- **Infrastructure Health** — daemon reachable? USB audio bound? host_agent up? Ports clean?
- **Interweaving Index** — how many cross-dimension flows work end-to-end (meeting + DoA + persona + gesture = 1 full interweaving)?
- **Backlog Debt** — count of `REQUESTS_LOG.md` items older than 14 days still `pending`.

### Grade scale

Same scale as `zero-deep-review`:

A+ (97–100), A (93–96), A- (90–92), B+ (87–89), B (83–86), B- (80–82), C+ (77–79), C (73–76), C- (70–72), D (60–69), F (0–59).

### ML learning model

The skill is not an LLM training loop. "ML learning" here means **persistent state that accumulates judgment across runs**:

1. **Scorecard history** — every audit snapshot goes to `history/`. Trend arrows surface regressions.
2. **Pattern promotion/demotion** — `LEARNINGS.md` tracks observed patterns. A pattern seen 2+ times with a reliable fix gets promoted into `SCORING_RUBRIC.md` as a checkable rule. A pattern that failed its fix twice gets demoted and flagged for architectural review.
3. **Request state machine** — `REQUESTS_LOG.md` entries move `pending → researched → planned → integrated → verified`. Each transition is dated and linked to a commit or PR. An entry stuck in `researched` for >14 days triggers a nudge.
4. **Integration-idea half-life** — `INTEGRATION_IDEAS.md` ideas that aren't picked up within 3 audits get auto-demoted to a `cold` section so the top stays fresh.

The system isn't learning weights; it's keeping a structured, dated memory that future audits consult instead of rediscovering. That's the contract: **every audit reads prior state, every audit leaves newer state.**

## Execution Protocol

Run the audit in six phases.

### Phase 0: Load prior state (2 min)

1. Read `knowledge/MASTER_SCORECARD.md` — capture last per-dimension score and date.
2. Read `knowledge/LEARNINGS.md` — scan for patterns flagged `[WATCH]` or `[PROMOTED]`.
3. Read `knowledge/REQUESTS_LOG.md` — list all `pending` and `researched` items.
4. Read `knowledge/INTEGRATION_IDEAS.md` — note ideas `hot` or aged out to `cold`.
5. If any of these files are missing, create them from the templates in `SCORING_RUBRIC.md` at the end of the run.

### Phase 1: Inventory the capability surface (5 min)

Rebuild `knowledge/CAPABILITIES_MAP.md` from source. Use **1 Explore agent** with this fixed brief:

> Inventory every Reachy-related file in `c:/code/zero`: services matching `reachy_*` or importing `reachy_service`, routers exposing `/api/reachy*` or `/api/home-assistant*`, scheduler jobs with `reachy_` prefix, frontend pages under `frontend/src/pages/Reachy*`, `frontend/src/components/reachy/*`, config keys in `infrastructure/config.py` matching `reachy_*` or `ha_*`, and external surfaces in `host_agent/` and `reachy_app/`. Report layer-by-layer with file paths and one-sentence purposes. End with a capability matrix (capability | implemented? | evidence).

Compare the new inventory to the prior `CAPABILITIES_MAP.md`:
- **New** files: log to `LEARNINGS.md` under *Additions this run*.
- **Removed** files: flag in the report.
- **Capability matrix deltas**: any `yes → partial` or `partial → no` is a regression and dominates the report.

### Phase 2: Grade the six dimensions (8 min)

For each of the six dimensions, run this exact protocol:

1. **Coverage check** — does the code cover the target capability surface listed in `SCORING_RUBRIC.md`? Count implemented vs target features. Score: `(implemented / target) * 100`.
2. **Quality scan** — for the files mapped to this dimension (from `CAPABILITIES_MAP.md`):
   - Count `except Exception:` (−3 each, max −30)
   - Count `TODO`/`FIXME`/`NotImplementedError` (−5 each, max −25)
   - Count `datetime.now()` without timezone (−10 each, max −30)
   - Count `print()` (−5 each, max −15)
   - Start at 100, floor at 0.
3. **Freshness check** — read `C:\code\reachy-apps\HARVEST_MANIFEST.md` if accessible. Check whether each Wave follow-up listed for this dimension is done. Score: `(completed_waves / listed_waves) * 100`.
4. **Observability check** — grep for `structlog.get_logger` usage in this dimension's files, presence of metrics emit, and an entry in `LEARNINGS.md`. Score rubric in `SCORING_RUBRIC.md`.
5. **Composite** — `coverage*0.40 + quality*0.25 + freshness*0.20 + observability*0.15`.

Write the six composites + sub-scores to `MASTER_SCORECARD.md` with a trend arrow vs last run (↑ / → / ↓, 5-point deadband).

### Phase 3: Upstream ecosystem scan (5 min, skippable)

Three sources, in order:

1. **Hugging Face Spaces** — query `https://huggingface.co/api/spaces?filter=reachy_mini_python_app&limit=500&full=true` (WebFetch). Diff against the cached list in `knowledge/history/hf_spaces_<last_date>.json`. Any space with `likes >= 5` that's not in `reachy-apps/community/` is a candidate for harvest.
2. **Pollen Robotics repos** — WebFetch `https://api.github.com/users/pollen-robotics/repos?per_page=100&sort=updated`. Flag any repo with commits in the last 30 days whose name starts with `reachy-mini` or `reachy_mini`.
3. **Pinned upstream projects** — check releases on:
   - `openwakeword` (wake-word model)
   - `pollen-robotics/reachy-mini-conversation-app` (persona source)
   - `pollen-robotics/reachy_mini_toolbox` (hand tracking)
   - `fcollonval/reachy_mini_wake_word` (scaffolded for voice loop)

Cache results under `knowledge/history/hf_spaces_YYYY-MM-DD.json` and `knowledge/history/pollen_repos_YYYY-MM-DD.json`. Add new candidates to `INTEGRATION_IDEAS.md` under *Upstream pickups*.

### Phase 4: Interweaving synthesis (5 min)

This is the creative pass. Identify cross-dimension flows that combine existing capabilities into something bigger. Four prompts to answer:

1. **What works today but isn't surfaced?** e.g., persona switching exists, context service exists, but there's no auto-persona-by-time-of-day (morning = friendly, evening = calm).
2. **What would a "day in the life" flow expose?** Trace: wake-up → morning briefing → pomodoros with gesture breaks → meeting attentiveness → email nudges → evening wind-down. Where does it break?
3. **Which partial capabilities block a whole flow?** e.g., vision exists but isn't wired to the daemon camera stream → blocks meeting "look at who's raising their hand" and teleop eye-contact.
4. **Which two-capability combos are one scheduler job away?** e.g., HA watcher + persona switch on "Living Room TV on" = cinema persona.

Output to `INTEGRATION_IDEAS.md` under *Interweavings*, each with:
- **Name**, **Dimensions touched**, **Minimum code delta**, **Why it's good**, **Blocking dependency** (if any), **Effort: S/M/L**, **State: hot/warm/cold**.

A new idea enters as `hot`. If it survives 3 audits without being actioned, it auto-ages to `warm`, then `cold`, then archived. The user can pin an idea via a `[PINNED]` tag to prevent aging.

### Phase 5: Request backlog triage (2 min)

For each entry in `REQUESTS_LOG.md`:

- `pending` — read the text, decide if it fits one of the 6 dimensions, map it to a `CAPABILITIES_MAP.md` row. If it maps cleanly: move to `researched` and link relevant upstream (from Phase 3). If it's a full new surface area: flag as `scoping_needed`.
- `researched` — does any upstream from Phase 3 unlock this? If so, move to `planned` with a fresh-prompt handoff attached (the handoff is a kickoff prompt the user can paste into a fresh chat).
- `planned` — skip unless the user explicitly actions it in this audit.
- `integrated` — verify the commit/PR is on main. If yes and tests pass, move to `verified`. If no, flag regression.
- `verified` — archive after 30 days into `knowledge/history/requests_archive.md`.

### Phase 6: Report + persist (3 min)

Write to stdout using the Report Format below. Then update:

1. `MASTER_SCORECARD.md` — new scores, new timestamp, trend arrows.
2. `LEARNINGS.md` — any new pattern observed this run (format: date, symptom, hypothesis, status).
3. `INTEGRATION_IDEAS.md` — new ideas from Phase 4, age transitions, upstream pickups from Phase 3.
4. `REQUESTS_LOG.md` — state transitions from Phase 5.
5. `history/YYYY-MM-DD-audit.md` — full snapshot (scores + counts + deltas) for future diffing.

## The `--ask` flow (file a new capability request)

When invoked as `/zero-reachy-audit --ask "description"`:

1. Append an entry to `REQUESTS_LOG.md`:
   ```markdown
   ## REQ-NNN: <title>
   - **Filed**: YYYY-MM-DD
   - **Raw ask**: "<description>"
   - **State**: pending
   - **Dimension guess**: <one of the 6, or "cross-cutting">
   - **Minimum delta**: <one sentence>
   - **Blocker**: <if known>
   - **Notes**: <anything learned during triage>
   ```
2. Do **not** run the full audit. Just triage this one request: run Phase 3 (upstream scan scoped to this ask) and Phase 4 (can it be achieved by interweaving existing capabilities?).
3. Print a short report: state, dimension, nearest upstream, recommended next step.

## The `--handoff <dim>` flow (fresh-prompt kickoff)

When the user wants to take a dimension deep in a fresh chat (e.g., meetings), this generates a self-contained kickoff document. The output goes to `knowledge/handoffs/YYYY-MM-DD-<dim>.md` and is printed to stdout.

Template:

```markdown
# Reachy <Dimension> Deep-Dive Handoff — YYYY-MM-DD

## Current score
<grade> (<composite>) — last audit <date>

## What's implemented
<bullet list from CAPABILITIES_MAP.md rows tagged to this dimension>

## Known gaps
<bullet list from MASTER_SCORECARD.md sub-scores + LEARNINGS.md watch items>

## Pending requests touching this dimension
<REQUESTS_LOG.md entries where dimension_guess == target>

## Upstream candidates
<INTEGRATION_IDEAS.md entries under "Upstream pickups" tagged to this dimension>

## Interweavings blocked by this dimension
<INTEGRATION_IDEAS.md entries whose "blocking dependency" is this dimension>

## Kickoff prompt (paste this into a fresh chat)
> I want to invest in Reachy's <dimension> capability. The zero-reachy-audit grade is
> <grade>. The three biggest gaps are: <top 3 sub-score deficits>. Start by reading
> .Codex/skills/zero-reachy-audit/knowledge/CAPABILITIES_MAP.md then propose a phased
> plan that closes those gaps, picks up <top upstream>, and unlocks <blocked interweaving>.
```

## Report Format

```
=== ZERO REACHY AUDIT ===
Timestamp: {YYYY-MM-DD HH:MM}
Mode: {full|quick|research|focus|ask|handoff}

OVERALL: {composite_grade} ({composite_score}/100)  trend: {↑|→|↓ vs last run}

DIMENSION SCORES:
  1. Motion & Body         {grade} ({score})  {arrow}
  2. Voice & Conversation  {grade} ({score})  {arrow}
  3. Persona & Emotion     {grade} ({score})  {arrow}
  4. Presence & Ambient    {grade} ({score})  {arrow}
  5. Meeting Mode          {grade} ({score})  {arrow}
  6. Environment & Integr. {grade} ({score})  {arrow}

CROSS-CUTTING:
  Infrastructure Health:  {status}  (daemon: {up|down}, host_agent: {up|down}, USB: {bound|missing})
  Interweaving Index:     {count} fully-working flows
  Backlog Debt:           {count} requests pending >14 days

REGRESSIONS ({count})
  - {dimension}: {score} → {score} ({delta}). Cause: {from LEARNINGS.md}

UPSTREAM UPDATES ({count new since last audit})
  - {HF Space | Pollen repo | pinned project}: {summary}, candidate for {dimension}

NEW INTEGRATION IDEAS ({count})
  - {title} ({dimensions}) — {effort} — {why}

REQUESTS PROGRESSED ({count})
  - REQ-NNN: {title} — {old_state} → {new_state}

TOP 3 NEXT STEPS
  1. {action with specific file/command}
  2. ...
  3. ...

HANDOFFS AVAILABLE
  - /zero-reachy-audit --handoff meeting     (regenerate meeting kickoff doc)
```

## Safety Rules

1. **Never restart the Reachy daemon.** It claims port 8000 and reloading it kills live audio/USB. Treat daemon reachability as read-only.
2. **Never modify `reachy_service.py` in the audit.** This skill only reads source — any code change must be a separate session with explicit user intent.
3. **Never delete or rename files in `C:\code\reachy-apps\`.** That's the reference mirror; it's a local git working copy used for harvest diffs.
4. **Upstream fetches are rate-limited.** HF Spaces query once per audit (500 results cap), GitHub API once per audit. Cache under `history/` and respect `If-Modified-Since` headers when available.
5. **Don't add a scheduler job from this skill.** If an interweaving suggests one, file it as a `planned` request instead.
6. **Secrets.** `ZERO_HA_TOKEN` / `ZERO_REACHY_WAKE_MODEL` never appear in knowledge files. If a config value must be referenced, use the env-var name, not the value.
7. **Grade conservatively.** A dimension is not 100 just because the files exist. 100 requires full coverage *and* zero quality deductions *and* all upstream waves integrated *and* full observability. Most dimensions should live in the B range.

## Common Dimension Anti-Patterns (seed `LEARNINGS.md`)

| Anti-pattern | Dimension | Detection | Fix direction |
|--------------|-----------|-----------|---------------|
| Gesture fires after TTS finishes (not during) | Persona & Emotion | Log timestamp between `parse_and_strip` and `play_emotion` > 500ms | Dispatch gesture in `asyncio.gather` with TTS, not after |
| Wake word off-thread blocks main loop | Voice & Conversation | `wake_loop.py` CPU > 50% single-core | Move to subprocess with shared-memory ring buffer |
| DoA angle drifts when antennas move | Meeting Mode | DoA reading + antenna position correlated | Fixed in daemon v1.6.4+; require `reachy-mini-daemon >= 1.6.4` |
| Presence beat runs while daemon offline | Presence & Ambient | 404s from daemon on every beat | Gate with `reachy_service.is_connected()` before dispatch |
| HA watcher eats API quota | Environment | Poll interval too aggressive | Respect `ZERO_HA_POLL_SECONDS`, back off on 429 |
| Motion library clip plays but aliasing fails | Motion & Body | LLM emits `[emotion:happy]`, daemon returns 404 | Alias resolver must fall back to `happy1` before giving up |

## First-Run Setup

If `knowledge/` is empty, the first `/zero-reachy-audit` run will:

1. Walk Phase 1 (Inventory) and write `CAPABILITIES_MAP.md` from scratch.
2. Initialize `MASTER_SCORECARD.md` with the first-run scores and no trend arrows (`—` for all).
3. Seed `LEARNINGS.md` from the Common Dimension Anti-Patterns table above (each one as `[WATCH]`).
4. Create empty `INTEGRATION_IDEAS.md`, `REQUESTS_LOG.md`, `history/` directory.
5. Note in the report: `FIRST RUN — no trend data yet. Re-run in ≥ 24 h for meaningful arrows.`

## Integration with Other Zero Skills

- Pairs with `/zero-docker-health` — that skill grades infra; this grades Reachy capability.
- Pairs with `/zero-deep-review` — that skill grades 20 Zero features (feature #11 is Meeting Intelligence, which overlaps with this skill's Meeting Mode dimension). When both run, prefer this skill's Meeting Mode score for Reachy-specific concerns.
- Pairs with `/zero-employee-checkin` — after an audit, it can pull the Reachy dimension grade into the daily stand-up.
- Does **not** overlap with `/zero-character-content` — character content is Zero's TikTok pipeline, unrelated to the robot.

## Exit Criteria for a "Done" Audit

Every successful run must satisfy:

- [ ] `MASTER_SCORECARD.md` updated with today's date
- [ ] `history/YYYY-MM-DD-audit.md` created
- [ ] `LEARNINGS.md` has ≥ 1 entry for this run (even "no new patterns")
- [ ] `REQUESTS_LOG.md` has every `pending` item either triaged or explicitly skipped with reason
- [ ] Report printed to stdout in the format above
- [ ] If any dimension regressed 5+ points, the report's `REGRESSIONS` section explains why

If any box is unchecked, the run is incomplete — rerun or finish the missing phase before declaring done.
