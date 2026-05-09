# Plan: Transform Paper Trading into an Autonomous, Self-Improving Trading Intelligence

## Context

**The Problem You're Describing (Rewritten):**

> "ADA's paper trading system is supposed to autonomously discover and trade the best opportunities. In practice, it's mostly mirroring my personal trades with small variance because the only signal source that actually works is my personal trades (60.9% WR, 907 of 1127 signals). The advisor agent (14% WR) and recommendation agent (0% WR) are broken, and XTrades is stale (no data in 25+ days). The ML learning pipeline exists but doesn't close the loop — models are trained but don't drive decisions. Backtesting exists but doesn't feed back into strategy parameters. The ADA Employee skill benchmarks performance but doesn't act on insights.
>
> I want ADA to be an independent, autonomous financial advisor that: (1) discovers its own trade opportunities from scanners, earnings, options flow, and market signals — not copying me, (2) uses a closed-loop ML pipeline where trade outcomes directly retrain models that improve future trades, (3) validates strategies via backtesting before deploying them, (4) has the ADA Employee act as the decision-making brain that continuously improves, and (5) has a review skill that periodically audits the whole system and generates improvement tasks."

**Evidence of the core problem:**
- Personal trades = 80% of all paper trade signals (907/1127)
- Advisor agent WR collapsed: 30.3% → 14% (all signal types regressed to ~50% = random)
- Recommendation agent: 0% WR, weight reduced to 0.2 across 7 adaptation cycles
- XTrades: frozen at 33 signals, no new data in 25+ days
- Calibration MAE was 60.8% (6x benchmark) — recently fixed to 6.6% via Platt Scaling
- ADA Employee benchmark: 49/100 — signal_accuracy=0, trade_quality=15

---

## Phase 1: Fix the Broken Signal Sources

**Goal:** Make the paper trading system independent of personal trades by fixing/adding autonomous signal sources.

### 1A. Fix the Unified AI Advisor (14% WR → 55%+)

**Root cause:** The 3-stage CoT pipeline generates predictions at random-chance accuracy. Every signal type (KEEP, ROLL, HOLD, CLOSE, SELL) regressed to ~50% WR.

**Files to modify:**
- [unified_ai_advisor.py](backend/services/unified_ai_advisor.py) — Fix LLM task routing in CoT stages, add calibration penalty to confidence output, filter recommendations by historical source reliability
- [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) — Replace static `DEFAULT_SOURCE_THRESHOLDS` with adaptive thresholds pulled from `source_accuracy` table

**Changes:**
1. Route CoT stages to appropriate TaskTypes (FINANCIAL_ANALYSIS for data, PLANNING for thesis)
2. Apply Platt-calibrated confidence adjustment to all recommendation confidence scores
3. Add source win-rate gate: if source WR < 40% over 50+ trades, suppress its signals entirely
4. Use Thompson Sampling when multiple sources recommend same symbol (explore/exploit balance)

### 1B. Resurrect XTrades Pipeline

**Files to modify:**
- [xtrades_sync_service.py](backend/services/xtrades_sync_service.py) — Diagnose why sync stopped (check Redis `xtrades:last_sync`, Discord channel access, rate limits)
- Add health check endpoint: `GET /api/xtrades/health` → `{last_sync, signals_24h, avg_confidence}`
- Add auto-recovery circuit breaker with exponential backoff

### 1C. Add 3 New Independent Signal Sources

**New files to create:**

1. **`backend/services/scanner_signal_generator.py`** — Converts strategy scanner results (`scanner_picks_cache` table) into paper trade signals. Filter: `composite_score > 80, mcdm_score > 70`. Route to auto_paper_trade_service with `source="scanner"`.

2. **`backend/services/earnings_signal_generator.py`** — Uses `earnings_power_rating` table to generate signals for stocks 3-7 days before earnings with power_rating > 75. Strategy: CSP for premium selling or directional for high-conviction.

3. **`backend/services/options_flow_signal_generator.py`** — Detects unusual options activity (large blocks, high volume/OI ratio, put/call skew anomalies) using Tradier options data. Generates "follow the smart money" signals.

**Database:** Add `options_flow_signals` table. Add index on `scanner_picks_cache(composite_score DESC)`.

### 1D. Dynamic Source Weighting

**File to modify:** [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py)

Replace static thresholds with Bayesian-adaptive thresholds:
- Source WR > 55% → lower conviction threshold (allow more signals from good sources)
- Source WR < 45% → raise threshold (be more selective)
- Source WR < 35% over 50+ trades → suppress entirely

Reuse existing: `source_accuracy` table, `ada_success_weights` table, Thompson Sampling from Employee skill (Phase Employee-02).

---

## Phase 2: Close the ML Learning Loop

**Goal:** Trade outcomes directly retrain models that improve future trade selection.

### 2A. Connect Backtesting → Strategy Parameters

**New file:** `backend/services/strategy_optimizer.py`

**Flow:** Backtest results → walk-forward optimization → find best profit_target/stop_loss per strategy → update `STRATEGY_EXIT_RULES` in auto_paper_trade_service → track in `strategy_parameters_history` table.

**Deployment gate:** Only deploy parameters where backtest Sharpe > 1.5, WR > 55%, max DD < 15%.

**Reuse:** [backtest_engine.py](backend/services/backtest_engine.py) (875 lines) already has walk-forward testing and Monte Carlo simulation.

### 2B. Paper Trade Outcomes → Model Retraining

**New file:** `backend/services/ml_retraining_trigger.py`

**Triggers for retraining:**
1. Every 100 closed paper trades
2. When 7d rolling win rate drops > 10% from 30d baseline
3. Weekly scheduled retrain (existing, but make it outcome-aware)

**Flow:** Paper trade closes → `outcome_learning_service.record_outcome()` (existing) → check trigger conditions → `ml_training_service.retrain_model()` → create new model version → A/B test (20% allocation to new model) → promote after 50 trades if outperforms.

**Reuse:** [ml_training_service.py](backend/services/ml_training_service.py) (1494 lines), [outcome_learning_service.py](backend/services/outcome_learning_service.py), [ml_training_scheduler.py](backend/services/ml_training_scheduler.py).

### 2C. Strategy Selection Engine

**New file:** `backend/services/strategy_selection_engine.py`

Picks which strategies to deploy based on current market regime + historical performance:
- Bull: momentum, trend-following, CSP on dips
- Bear: premium selling (CSP, CC), defensive
- High vol: avoid long premium, favor selling
- Neutral: Iron Condor, Butterfly, CSP

**Database:** Create `strategy_regime_performance` table tracking WR/Sharpe/DD per strategy per regime.

---

## Phase 3: Build the Autonomous Trading Brain

**Goal:** ADA runs a daily autonomous cycle: scan → score → select → size → execute → monitor → learn.

### 3A. Daily Autonomous Cycle

**New file:** `backend/services/autonomous_trading_brain.py`

**Daily cycle (runs during market hours):**
1. **SCAN** — Run all signal generators (scanner, earnings, options flow, XTrades, advisor)
2. **SCORE** — Run conviction engine on each signal, require overall_score >= 70
3. **SELECT** — Filter by active strategies from regime router, take top 10 signals
4. **SIZE** — Kelly Criterion position sizing (existing) blended with DRL recommendation
5. **EXECUTE** — Submit to auto_paper_trade_service for execution via Tradier sandbox
6. **MONITOR** — Check existing positions for exit triggers (profit target, stop loss, DTE)
7. **LEARN** — Check ML retraining triggers, update source weights

**Reuse:** [conviction_engine.py](src/ada/langgraph/graphs/conviction_engine.py) (989 lines), [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py), [paper_trade_monitor.py](backend/services/paper_trade_monitor.py).

### 3B. Wire Conviction Engine into Pipeline

**File to modify:** [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py)

Add conviction pre-filter before `should_auto_trade()`:
- Run `conviction_engine.process_conviction_alert()` on each candidate
- Reject if `recommendation in ["avoid", "strong_avoid"]`
- Reduce position size by 50% if bull/bear debate gap > 30 (high disagreement)

### 3C. Elevate ADA Employee to Decision-Maker

**File to modify:** [ada_employee_service.py](backend/services/ada_employee_service.py)

New capability: Self-Improvement Execution Cycle
1. Compute benchmark (existing)
2. Identify weakest dimension (existing)
3. Generate improvement plan using LLM (new)
4. Execute improvement by calling relevant service APIs (new)
5. Schedule re-benchmark in 24h (new)
6. Track improvement delta in `ada_employee_improvement_cycles` table (new)

**Update skill:** [.claude/skills/ada-employee/SKILL.md](.claude/skills/ada-employee/SKILL.md) — Add `--cycle` mode that runs the improvement execution cycle.

---

## Phase 4: Build the Review & Improvement Skill

**Goal:** A periodic review skill that audits the autonomous system and generates improvement tasks.

### 4A. Create `/review-paper-trading` Skill

**New directory:** `.claude/skills/paper-trading-review/`

**Skill analyzes:**
1. Win rate trends by source, strategy, symbol (7d/30d/90d rolling)
2. Model accuracy drift detection (CUSUM, sequential hypothesis testing)
3. Strategy performance vs backtest expectations
4. Portfolio-level risk metrics (Sharpe, max DD, Calmar)
5. Comparison to buy-and-hold SPY benchmark
6. Source independence metric (% signals from personal trades — target < 20%)
7. Learning velocity (is the system getting better over time?)

**Output:** Structured report with:
- Overall health grade (A-F)
- Top 3 improvement recommendations
- Auto-generated sprint tasks for the improvements
- Drift alerts for any degrading components

### 4B. Performance Drift Detector

**New file:** `backend/services/performance_drift_detector.py`

Methods:
- Sequential Probability Ratio Test (SPRT) for win rate degradation
- CUSUM control chart for sustained P&L drift
- KS test for return distribution shift

Generates alerts in `performance_alerts` table when drift detected.

---

## Phase 5: Dashboard & Observability

### 5A. Enhanced Paper Trading Dashboard

**New endpoints:**
- `GET /api/paper-trading/autonomous-stats` — ADA's autonomous performance vs user's personal
- `GET /api/paper-trading/source-breakdown` — Per-source WR, trade count, trend
- `GET /api/paper-trading/active-strategies` — Current regime + active strategy list
- `GET /api/paper-trading/learning-velocity` — Rolling WR, Sharpe, improvement rate

**Frontend:** Add comparison cards to [PaperTradingHub.tsx](frontend/src/pages/PaperTradingHub.tsx) showing autonomous picks vs personal trades side-by-side.

### 5B. Live Decision Feed

WebSocket endpoint showing real-time autonomous decisions:
- "ADA opened CSP on NVDA $850P 5/16 — Conviction: 82, Regime: Bull, Scanner source"
- "ADA closed AAPL position — 50% profit target hit after 3 days"
- "ADA rejected TSLA signal — advisor source WR below threshold (14%)"

---

## Success Metrics

| Metric | Current | 1-Month Target | 3-Month Target |
|--------|---------|----------------|----------------|
| Source independence (% non-personal) | 20% | 50% | 80% |
| Autonomous win rate | N/A | 50% | 55%+ |
| Sharpe ratio | ~0 | 0.8 | 1.5+ |
| Max drawdown | uncontrolled | <15% | <12% |
| ADA Employee benchmark | 49/100 | 60/100 | 70/100 |
| Active signal sources | 1 (personal) | 4+ | 5+ |
| ML model retrains | manual | every 100 trades | continuous |
| Calibration MAE | 6.6% | <5% | <3% |

---

## Execution Configuration

**Scope:** Full vision — all 5 phases, implemented incrementally
**Autonomy:** Full autopilot — ADA independently scans, selects, sizes, and executes paper trades. User reviews results after the fact. This is paper money — let it learn fast.

**Autopilot defaults for `autonomous_executor.py`:**
- `execution_mode: "paper"` (never live without explicit user opt-in)
- `enabled: true` (autopilot ON)
- `dry_run: false` (actually execute paper trades)
- `require_minimum_conviction: 0.70` (lowered from 0.85 to allow more learning volume)
- `max_concurrent_positions: 10` (raised from 3 to allow diverse portfolio)
- `max_single_trade_dollars: $2000` (raised from $1000 for meaningful position sizes)
- `cooldown_consecutive_losses: 5` (raised from 3 — tolerate more losses during learning)

**Phase execution order:** 1 → 2 → 3 → 4 → 5 (sequential, each builds on prior)

---

## Verification Plan

After each phase:
1. **Phase 1:** Verify new signal sources generate signals independently — query `alert_paper_trades` and confirm `signal_source` distribution is diversified (< 50% personal)
2. **Phase 2:** Run backtest → verify strategy parameters update → verify next paper trade uses updated parameters
3. **Phase 3:** Let autonomous cycle run for 48h → verify `autonomous_daily_cycles` table logs complete cycles → check paper trade positions opened without personal trade input
4. **Phase 4:** Run `/review-paper-trading` skill → verify it produces actionable report with improvement recommendations
5. **Phase 5:** Navigate to paper trading dashboard → verify comparison cards show autonomous vs personal performance

**End-to-end test:** Disable personal trade signal source → verify ADA still generates and executes paper trades from scanner, earnings, options flow, and XTrades sources alone.
