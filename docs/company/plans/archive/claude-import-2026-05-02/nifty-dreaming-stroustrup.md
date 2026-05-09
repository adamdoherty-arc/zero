# ADA Employee Skill — Deep Review & Improvement Plan

## Context

The ADA Employee skill was deployed on 2026-04-12 as a v2 evolution of the ada-theta-advisor skill. It expands from pure options advisory to a comprehensive AI financial advisor + system manager with a 10-dimension benchmark. The first baseline scored **39.5/100** with 3 dimensions at zero. This plan addresses correctness issues in the current implementation, fills functional gaps from the skill spec, and incorporates state-of-the-art research on AI financial advisory systems to make this the best possible self-improving financial advisor.

---

## Part 1: Bug Fixes & Correctness (Must-Do)

### 1.1 Fix Redis/Qdrant connection leaks in system_awareness scorer
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- Lines 748-756: Redis client created per-call with no pooling, only `aclose()` in happy path
- Lines 770-778: Qdrant client created per-call (synchronous), no cleanup
- Lines 956-965: Same Redis pattern in `generate_health_digest()`
- Lines 968-975: Same Qdrant pattern in digest
- **Fix**: Import existing infrastructure clients (`backend/infrastructure/cache.py` for Redis, use `is_rag_available()`/`get_rag()` for Qdrant) instead of creating ad-hoc connections. Wrap in try/finally for cleanup.

### 1.2 Fix hardcoded calibration file path
**Files**: [ada_employee_service.py:599](backend/services/ada_employee_service.py#L599)
- Falls back to `c:/code/ada/.claude/skills/ada-theta-advisor/knowledge/calibration.json` — Windows-specific, breaks in Docker
- **Fix**: Use `os.path.join()` relative to project root from config, or better yet, only use the DB table (the file fallback was for bootstrap and can be removed now that DB table is populated)

### 1.3 Fix acknowledgment result parsing
**Files**: [ada_employee_service.py:168](backend/services/ada_employee_service.py#L168)
- `return "UPDATE 1" in str(result)` is brittle — asyncpg returns command tag string but format varies
- **Fix**: Use `result == "UPDATE 1"` or parse via `int(result.split()[-1]) > 0`

### 1.4 Fix timezone handling consistency
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py) (lines 260, 519, 988)
- `.replace(tzinfo=UTC if last_sync.tzinfo is None else last_sync.tzinfo)` — if tzinfo is already set, this is a no-op; if not, it attaches UTC without conversion
- **Fix**: Use a helper `def _ensure_utc(dt)` that handles both naive and aware datetimes correctly

### 1.5 Fix N+1 queries on source_accuracy table
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- `source_accuracy` is queried independently in `_score_trade_quality` (L325), `_score_signal_accuracy` (L414, L425), `_score_learning_velocity` (L527, L539)
- **Fix**: Pre-load all source_accuracy rows once at the start of `compute_benchmark()` and pass to each scorer

---

## Part 2: Missing Functionality (Skill Spec Gaps)

### 2.1 Create `applied_improvements.md` knowledge file
**Files**: New file at `.claude/skills/ada-employee/knowledge/applied_improvements.md`
- Referenced in skill spec but doesn't exist
- Seed with Employee-00 baseline entry

### 2.2 Add morning briefing endpoint
**Files**: [ada_employee.py](backend/routers/ada_employee.py), [ada_employee_service.py](backend/services/ada_employee_service.py)
- Skill spec defines `--morning-briefing` mode but no endpoint exists
- **Add**: `GET /api/ada-employee/morning-briefing` that aggregates:
  - Portfolio positions with overnight changes (from `cached_stock_positions`)
  - Market regime (from `market_regime_current` or cache)
  - Upcoming earnings for held positions (from `earnings_calendar`)
  - Active alerts summary (from `trade_alerts`)
  - Risk exposure summary (top position concentrations, Greeks totals)
  - Today's recommended actions (positions at risk: ITM, <5 DTE, earnings within 3 days)

### 2.3 Add proactive message generation triggers
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- 6 message types defined but no code generates them automatically
- **Add** `generate_proactive_checks()` method that:
  - Scans for ITM options with <5 DTE → `employee_risk_warning`
  - Checks if calibration MAE worsened → `employee_calibration_alert`
  - Detects service health degradation → `employee_system_alert`
  - Generates daily digest if not sent today → `employee_daily_digest`
- **Wire to**: Either a scheduled task (via existing scheduler pattern) or call from `/benchmark/save`

### 2.4 Add audit endpoint
**Files**: [ada_employee.py](backend/routers/ada_employee.py), [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Add**: `GET /api/ada-employee/audit` that returns comprehensive system audit:
  - All service health checks (DB, Redis, Qdrant, Ollama)
  - Data freshness for all critical tables (positions, signals, alerts, outcomes, calibration)
  - Agent performance summary (from `source_accuracy` and `signal_source_performance`)
  - Scheduler status (adaptation engine, alert engine, position sync)
  - Recent error counts from logs (if accessible via DB)

### 2.5 Add persona management endpoints
**Files**: [ada_employee.py](backend/routers/ada_employee.py), [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Add**: `GET /api/ada-employee/persona` returns current `persona_config.json`
- **Add**: `PUT /api/ada-employee/persona` updates specific persona fields
- Store persona in DB (new table `ada_employee_persona`) with file as fallback

---

## Part 3: Calibration Fix (Priority #1 — Research-Backed)

### 3.1 Implement Platt Scaling calibrator
**Files**: New service at `backend/services/calibration_service.py`
- **Problem**: MAE 56.2%, inverted confidence (0-20% predicted → 84.6% actual, 90-100% predicted → 49% actual)
- **Solution**: Platt Scaling (logistic regression with 2 parameters) — optimal for N=816 samples per Cornell calibration research
- **Implementation**:
  1. Collect all (predicted_confidence, actual_outcome) pairs from `xtrades_signal_outcomes` + `recommendation_outcomes`
  2. Fit `sklearn.linear_model.LogisticRegression` on raw scores → actual outcomes
  3. Store fitted parameters (a, b) in `ada_confidence_calibration` table as a "platt_model" row
  4. Apply to all new confidence scores before surfacing: `calibrated = sigmoid(a * raw + b)`
  5. Re-compute MAE after applying — target: MAE < 15%
- **Add endpoint**: `POST /api/ada-employee/calibrate` to trigger recalibration
- **Add endpoint**: `GET /api/ada-employee/calibration-status` to show current MAE, sample count, model params

### 3.2 Fix calibration bucket bugs
**Files**: [calibration.json](/.claude/skills/ada-theta-advisor/knowledge/calibration.json), calibration service
- Normalize to non-overlapping decile buckets: 0-10, 10-20, ..., 90-100
- Cap all confidence scores at [0.0, 1.0] — eliminate >100% values
- Per-source calibration: separate Platt models for `personal`, `advisor`, `options_flow`, `xtrades_signal`

### 3.3 Add source-level circuit breaker
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Current**: Recommendation agent at 0% WR slowly attenuated from 0.9→0.2 over 7 cycles (too slow)
- **Fix**: Hard circuit breaker — if win_rate < 25% over 30+ samples, set weight = 0.0 immediately
- Re-activation: require 10 paper-trade signals with > 50% WR before real capital allocation

---

## Part 4: Self-Improvement Framework (Research-Backed)

### 4.1 Implement Bayesian weight updates (replace fixed-step)
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py) or new `backend/services/bayesian_weighting_service.py`
- **Current**: Fixed +/- 0.01-0.03 step per adaptation cycle (slow convergence)
- **Better**: Thompson Sampling via Beta distributions — `np.random.beta(wins+1, losses+1)` per source, softmax normalization
- Naturally handles uncertainty (fewer samples → wider distribution → more exploration)
- Converges to optimal weights faster than fixed-step

### 4.2 Add Reflexion-based weekly self-analysis
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Add** `generate_weekly_reflection()` method:
  1. Analyze all losing trades from past 7 days
  2. Identify common patterns (sector, regime, signal combo, time-of-day)
  3. Generate natural-language lesson via Ollama
  4. Store in `knowledge/LEARNINGS.md` automatically
  5. Update `advisory_patterns.md` if new rule discovered
- **Trigger**: Weekly scheduler or manual `POST /api/ada-employee/reflect`

### 4.3 Add benchmark trend tracking with goal-setting
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Current**: Saves snapshots but doesn't track trends or set goals
- **Add**: `GET /api/ada-employee/benchmark/trend` returns:
  - Score history for each dimension (last 10 benchmarks)
  - Trend direction (improving/declining/stable) per dimension
  - Velocity (rate of change per week)
  - Auto-generated goal: "Improve {weakest_dimension} from {current} to {target} by {date}"

---

## Part 5: Proactive Advisory Upgrade (Research-Backed)

### 5.1 Add time-critical proactive checks (intraday)
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Options Expiration Management**: 3 DTE, 1 DTE, 0 DTE alerts for open options
- **Earnings Proximity Warning**: T-5, T-3, T-1 for held positions
- **Volatility Regime Shift**: VIX crossing 15/20/25/30 thresholds
- Each generates a proactive message via `add_message()` with appropriate kind/priority

### 5.2 Add portfolio health composite score
**Files**: New method in [ada_employee_service.py](backend/services/ada_employee_service.py)
- **6-sub-dimension composite** (0-100 each, weighted):
  - Concentration (20%): HHI-based, max single position %
  - Correlation (15%): Avg pairwise correlation across holdings
  - Greeks Exposure (20%): Portfolio delta/gamma/theta/vega vs NLV
  - Sector Tilt (15%): Max sector %, deviation from target
  - Drawdown Risk (15%): Current drawdown, VaR estimate
  - Liquidity (15%): ADV coverage, bid-ask spread
- **Add endpoint**: `GET /api/ada-employee/portfolio-health`
- Replaces the simplistic position-count-based scoring in dimension 4

### 5.3 Add opportunity scanner
**Files**: [ada_employee_service.py](backend/services/ada_employee_service.py)
- **Add**: `GET /api/ada-employee/opportunities` — proactively surface best CSP/CC candidates
- Uses existing `position_opportunities_service.py` data + IV rank + portfolio fit analysis
- Filters for market regime alignment
- Generates `employee_trade_opportunity` proactive messages for top 3-5 candidates

---

## Part 6: Skill File Improvements

### 6.1 Update SKILL.md with endpoint documentation
- Add complete API reference section listing all endpoints (current 6 + planned new ones)
- Add data flow diagram showing how benchmark → proactive messages → learning loop connects

### 6.2 Update knowledge files after implementation
- `LEARNINGS.md`: Add Employee-01 entry with calibration fix results
- `advisory_patterns.md`: Add new rules discovered during implementation
- `benchmark_scores.json`: Save new benchmark after all improvements
- Create `applied_improvements.md` with Employee-00 through Employee-0N entries

---

## Implementation Order (Priority)

| Phase | Items | Impact | Effort |
|-------|-------|--------|--------|
| **1** | 1.1-1.5 (bug fixes) | Correctness, prevent connection leaks | Small |
| **2** | 3.1-3.3 (calibration fix) | MAE 56% → <15%, fixes #1 crisis | Medium |
| **3** | 2.2-2.3 (morning briefing + proactive messages) | Communication dim 0 → 60+ | Medium |
| **4** | 4.1 (Bayesian weights) | Faster convergence, better exploration | Small |
| **5** | 2.4-2.5 (audit + persona endpoints) | Complete skill spec coverage | Small |
| **6** | 5.1-5.3 (proactive advisory upgrade) | Differentiated advisor capabilities | Large |
| **7** | 4.2-4.3 (reflection + trends) | Self-improvement flywheel | Medium |
| **8** | 6.1-6.2 (skill file updates) | Documentation, tracking | Small |

## Expected Benchmark Impact

| Dimension | Current | After Phase 1-3 | After All |
|-----------|---------|-----------------|-----------|
| portfolio_health | 65 | 70 | 80+ |
| trade_quality | 15 | 25 | 50+ |
| signal_accuracy | 0 | 20 | 60+ |
| risk_management | 55 | 60 | 80+ |
| learning_velocity | 60 | 65 | 80+ |
| advisory_calibration | 45 | 75 | 85+ |
| communication | 0 | 55 | 75+ |
| system_awareness | 85 | 90 | 90+ |
| response_quality | 50 | 55 | 65+ |
| rag_knowledge | 50 | 50 | 60+ |
| **Overall** | **39.5** | **55+** | **75+** |

## Verification

1. **After bug fixes**: `docker restart ada-backend` → `curl http://localhost:8006/api/ada-employee/benchmark` returns all 10 dimensions without errors
2. **After calibration fix**: `curl http://localhost:8006/api/ada-employee/calibration-status` shows MAE < 15%
3. **After proactive messages**: `curl http://localhost:8006/api/ada-employee/proactive?acknowledged=false` shows generated messages
4. **After morning briefing**: `curl http://localhost:8006/api/ada-employee/morning-briefing` returns portfolio + market + alerts + actions
5. **After all phases**: `POST /api/ada-employee/benchmark/save` → overall score > 70

## Critical Files

| File | Purpose |
|------|---------|
| [backend/routers/ada_employee.py](backend/routers/ada_employee.py) | API router — add new endpoints |
| [backend/services/ada_employee_service.py](backend/services/ada_employee_service.py) | Core service — fix bugs, add methods |
| [backend/alembic/versions/20260412_ada_employee_tables.py](backend/alembic/versions/20260412_ada_employee_tables.py) | DB migration — may need new tables |
| [.claude/skills/ada-employee/SKILL.md](.claude/skills/ada-employee/SKILL.md) | Skill definition |
| [.claude/skills/ada-employee/knowledge/LEARNINGS.md](.claude/skills/ada-employee/knowledge/LEARNINGS.md) | Accumulated learnings |
| [.claude/skills/ada-employee/knowledge/advisory_patterns.md](.claude/skills/ada-employee/knowledge/advisory_patterns.md) | Codified rules |
| [.claude/skills/ada-employee/knowledge/benchmark_scores.json](.claude/skills/ada-employee/knowledge/benchmark_scores.json) | Score history |
| [.claude/skills/ada-employee/knowledge/persona_config.json](.claude/skills/ada-employee/knowledge/persona_config.json) | Persona configuration |
| [backend/infrastructure/cache.py](backend/infrastructure/cache.py) | Redis infrastructure (reuse) |
| [backend/infrastructure/database.py](backend/infrastructure/database.py) | DB infrastructure (reuse) |

## Existing Code to Reuse

| Need | Existing Implementation |
|------|----------------------|
| Redis connection | `backend/infrastructure/cache.py` — `get_redis()` or `RedisCache` |
| Qdrant check | `src/rag/` — `is_rag_available()`, `get_rag()` |
| Market regime | `backend/services/market_regime_agent.py` — cached regime data |
| Earnings calendar | `backend/services/earnings_calendar_service.py` |
| Options positions | `backend/services/portfolio_service.py` — `get_option_positions()` |
| Position opportunities | `backend/services/position_opportunities_service.py` |
| LLM for reflection | `backend/infrastructure/llm_router.py` — `get_chat_openai(TaskType.ANALYSIS)` |
