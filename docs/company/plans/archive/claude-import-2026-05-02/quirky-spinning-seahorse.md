# ADA Employee Skill — AI Financial Advisor

## Context

The Legion Employee skill achieved 99.4/100 across 9 dimensions over 29 sprints — a proven self-improvement pattern. The user wants to adapt this for ADA as a **financial advisor employee** that manages the entire ADA trading platform, evaluates trades, monitors alerts, and continuously learns to give better advice. The skill goes at `c:\code\ada\.claude\skills\ada-employee/`.

ADA has 170+ services, 60+ routers, 134+ DB tables, a Redis Streams event bus with 50+ event types, a learning adaptation engine running daily, Qdrant RAG with 768-dim embeddings, and rich trade data (907+ personal trades, 1127+ signals, calibration data). This is MUCH richer data than Legion had — the benchmark can score from real data on day 1.

### Pros of Adapting Legion Employee to ADA
1. **Proven pattern** — 99.4/100 validated across 29 sprints; skip the trial-and-error
2. **Content-hash dedup + escalation** — Domain-agnostic, directly portable
3. **Version-tracked benchmark** — Prevents score inflation (Legion's honest re-audit at v5 caught inflation)
4. **ADA has richer data** — 907+ trades, calibration buckets, 16 adaptation cycles; scores can use real data immediately
5. **Compatible infrastructure** — Redis Streams event bus, asyncpg, Qdrant all already running

### Cons and Mitigations
1. **Different DB pattern** — ADA uses raw asyncpg via `get_database()`, not SQLAlchemy ORM. All queries must use raw SQL (mitigated: follow accuracy_tracker.py pattern)
2. **No sprint self-improvement system in ADA** — Log to `applied_improvements.md` + benchmark_scores.json instead
3. **Broken calibration scores low initially** — MAE 60.8% means calibration dimension starts at ~15/100. That's honest; the self-improvement loop drives fixes upstream
4. **Overlap with advisor-audit skill** — Employee grades ITSELF as an advisor; advisor-audit grades the SYSTEM's features. Clear differentiation
5. **Notification noise** — Use distinct `kind` prefixes (`employee_*`) to avoid overlap with proactive_intelligence_engine

---

## File Plan

### Skill Files (`c:\code\ada\.claude\skills\ada-employee/`)

| File | Description |
|------|-------------|
| `SKILL.md` | Persona, 10 benchmark dimensions, context-gathering curl commands, modes (--status, --research, --improve, --audit, --morning-briefing), execution protocol, learning protocol |
| `knowledge/benchmark_scores.json` | Version-tracked history (seed as v0 with empty history) |
| `knowledge/system_map.md` | Complete map of ADA's services, routers, agents, tables, event bus, scheduler jobs |
| `knowledge/LEARNINGS.md` | Seeded from theta-advisor's 5 learning reviews (carry forward real data) |
| `knowledge/advisory_patterns.md` | Codified patterns: regime-aware positioning, source reliability weighting, calibration discipline |
| `knowledge/persona_config.json` | Financial advisor identity, communication style, confidence thresholds |

### Backend Files (`c:\code\ada\backend/`)

| File | Description |
|------|-------------|
| `services/ada_employee_service.py` | Core service: benchmark computation (10 dimensions from live DB), proactive messaging (add/list/acknowledge), content-hash dedup, escalation (3x unack -> ACTION_REQUIRED), event bus subscription |
| `routers/ada_employee.py` | 6 API endpoints (see below) |
| `alembic/versions/20260412_ada_employee_tables.py` | Migration: `ada_proactive_messages` + `ada_employee_benchmark_history` tables |

---

## 10 Benchmark Dimensions

| # | Dimension | Weight | What It Measures | Data Source |
|---|-----------|--------|-----------------|-------------|
| 1 | portfolio_health | 12% | Position sync recency, Greeks populated, P&L tracking | `positions` table + `/api/portfolio/positions/enriched` |
| 2 | trade_quality | 15% | Win rates improving, outcome tracking active, source separation | `signal_outcomes` table via accuracy_tracker.py |
| 3 | signal_accuracy | 12% | Alert-to-trade conversion, ML scoring active, best/worst sources | `unified_alerts` + `signal_outcomes` join |
| 4 | risk_management | 10% | Single-position exposure, sector concentration, VaR active | `positions` + `/api/advanced-risk/portfolio-risk` |
| 5 | learning_velocity | 15% | Adaptation cycles running, weights trending correctly, scheduler healthy | `adaptation_weights` + weights.json trajectory |
| 6 | advisory_calibration | 15% | Confidence matches outcomes (MAE), bucket data populated | calibration.json + `/api/learning/calibration/summary` |
| 7 | communication | 8% | Proactive messages generated (>5/wk), all acknowledged, morning briefings | `ada_proactive_messages` table (new) |
| 8 | system_awareness | 5% | Backend healthy, DB connected, Redis up, learning scheduler alive, Qdrant up | `/api/health` + service checks |
| 9 | response_quality | 5% | Brain response time, user feedback ratings, context-aware responses | `brain_conversations` + AI feedback data |
| 10 | rag_knowledge | 3% | Qdrant operational, signals indexed, temporal decay applied | Qdrant stats + `xtrades_signals` |

**Calibration (dim 6) is intentionally weighted highest at 15%** because it's the #1 crisis (MAE 60.8%, confidence inverted at extremes). High weight drives improvement sprint priority.

---

## API Endpoints

Router prefix: `/api/ada-employee`, registered in `main.py` via `app.include_router(ada_employee.router)`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/benchmark` | Compute all 10 dimensions live. Returns `{overall, dimensions, evidence, computed_at}` |
| `GET` | `/proactive` | List messages. Params: `limit=50, acknowledged=null/true/false, kind=null` |
| `POST` | `/proactive/{id}/acknowledge` | Acknowledge a message |
| `GET` | `/health-digest` | System health summary (services, scheduler, data freshness) |
| `GET` | `/trade-digest` | Trade eval summary (win rates by source, calibration MAE, top/worst symbols) |
| `POST` | `/benchmark/save` | Persist benchmark to DB + benchmark_scores.json |

---

## Database Migration

### `ada_proactive_messages`
```sql
CREATE TABLE ada_proactive_messages (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(50) NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'info',
    title VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    metadata_json JSONB,
    content_hash VARCHAR(64),
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Indexes: unread(acknowledged, created_at), kind(kind, created_at), content_hash(content_hash, created_at)
```

### `ada_employee_benchmark_history`
```sql
CREATE TABLE ada_employee_benchmark_history (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    overall_score DECIMAL(5,2) NOT NULL,
    dimensions JSONB NOT NULL,
    evidence JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);
```

Migration follows ADA's Alembic pattern (e.g., `20260317_learning_alerts.py` — raw SQL via `op.execute()`).

---

## Backend Service Architecture

`ada_employee_service.py` follows the `accuracy_tracker.py` pattern:
- `from backend.infrastructure.database import get_database` for all DB access
- Each benchmark dimension is a separate `async def _score_X(self) -> tuple[int, dict]` returning (score, evidence)
- Proactive messaging: `_add_message()`, `get_proactive_messages()`, `acknowledge_message()`
- Content-hash dedup: SHA-256 of `kind+title+body[:200]`, 1h window
- Escalation: 3x unacknowledged of same `kind` within 24h -> priority bumps to `action_required`
- Event bus: Subscribe to `EventType.ALERT_HIGH_PRIORITY`, `EventType.POSITION_AT_RISK`, `EventType.LEARNING_MILESTONE`, `EventType.PAPER_TRADE_CLOSED` to generate proactive messages

---

## Integration Points (existing services, NO duplication)

| Existing | How Employee Uses It |
|----------|---------------------|
| `accuracy_tracker.py` | Call `get_source_accuracy()` for trade_quality + signal_accuracy dimensions |
| `alert_hub_service.py` | Read alert counts/sources for signal_accuracy dimension |
| `ada_learning_scheduler.py` | Read scheduler status for learning_velocity dimension |
| `portfolio_service.py` | Read positions for portfolio_health + risk_management dimensions |
| `calibration.json` (theta-advisor knowledge) | Read calibration buckets for advisory_calibration dimension |
| `event_bus.py` | Subscribe via consumer group for proactive message generation |
| `qdrant_config.py` | Read collection stats for rag_knowledge dimension |
| `ada_brain_service.py` | Read conversation stats for response_quality dimension |

---

## Implementation Order

### Phase 1: Skill Files (no backend, immediate skill invocability)
1. Create `SKILL.md` — persona, dimensions, curl commands, modes, learning protocol
2. Create `knowledge/benchmark_scores.json` — v0 seed with dimension weights/descriptions
3. Create `knowledge/system_map.md` — ADA service/router/agent/table map
4. Create `knowledge/LEARNINGS.md` — seeded from theta-advisor's 5 reviews
5. Create `knowledge/advisory_patterns.md` — codified advisory patterns
6. Create `knowledge/persona_config.json` — advisor identity config

### Phase 2: Database + Backend
7. Create Alembic migration for 2 tables
8. Create `ada_employee_service.py` with all 10 dimension scorers + proactive messaging
9. Create `routers/ada_employee.py` with 6 endpoints
10. Register router in `main.py`
11. Wire event bus subscriptions in startup

### Phase 3: Verification
12. Apply migration, rebuild, test `/api/ada-employee/benchmark`
13. Verify proactive message flow (insert, list, acknowledge)
14. Run first benchmark and save as v1 in knowledge/benchmark_scores.json
15. Identify weakest dimension — that becomes the first improvement target

---

## Verification Plan

```bash
# 1. Migration applied
docker exec ada-db psql -U ada -d ada -c "SELECT COUNT(*) FROM ada_proactive_messages;"

# 2. Benchmark endpoint returns real scores
curl -s http://localhost:8006/api/ada-employee/benchmark | python -m json.tool

# 3. Proactive messages CRUD
curl -s http://localhost:8006/api/ada-employee/proactive
curl -s -X POST http://localhost:8006/api/ada-employee/proactive/1/acknowledge

# 4. Trade digest shows real win rates
curl -s http://localhost:8006/api/ada-employee/trade-digest | python -m json.tool

# 5. Health digest shows service statuses
curl -s http://localhost:8006/api/ada-employee/health-digest | python -m json.tool
```

---

## Key Files to Modify/Create

**Create (new):**
- `c:\code\ada\.claude\skills\ada-employee\SKILL.md`
- `c:\code\ada\.claude\skills\ada-employee\knowledge\benchmark_scores.json`
- `c:\code\ada\.claude\skills\ada-employee\knowledge\system_map.md`
- `c:\code\ada\.claude\skills\ada-employee\knowledge\LEARNINGS.md`
- `c:\code\ada\.claude\skills\ada-employee\knowledge\advisory_patterns.md`
- `c:\code\ada\.claude\skills\ada-employee\knowledge\persona_config.json`
- `c:\code\ada\backend\services\ada_employee_service.py`
- `c:\code\ada\backend\routers\ada_employee.py`
- `c:\code\ada\backend\alembic\versions\20260412_ada_employee_tables.py`

**Modify (existing):**
- `c:\code\ada\backend\main.py` — Add `include_router(ada_employee.router)` + import

**Reference (read-only, patterns to follow):**
- `c:\code\ada\backend\services\accuracy_tracker.py` — DB access pattern (`get_database()`, raw SQL)
- `c:\code\ada\backend\infrastructure\event_bus.py` — EventType enum, subscription pattern
- `c:\code\ada\backend\alembic\versions\20260317_learning_alerts.py` — Migration pattern
- `c:\code\ada\.claude\skills\ada-theta-advisor\SKILL.md` — Skill format
- `c:\code\Legion\.claude\skills\legion-employee\knowledge\benchmark_scores.json` — Benchmark history format
- `c:\code\Legion\backend\app\services\legion_employee_service.py` — Proactive messaging pattern
