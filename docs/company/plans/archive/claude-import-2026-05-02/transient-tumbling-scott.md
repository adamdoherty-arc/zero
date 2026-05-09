# Plan: Take All 13 Advisor Audit Dimensions to 100/100

## Context
The advisor audit (run #13) scored ADA at **87/100** (13-dim) / **94/100** (10-dim). Three new dimensions (Paper Trading: 30, Backtesting: 25, Execution Quality: 38) revealed critical gaps in real-world trading validation. The original 10 dimensions range from 90-97. This plan closes all gaps across 5 phases ordered by weighted impact.

## Weighted Gap Priority

| Dim | Score | Gap | Weight | Weighted Gap |
|-----|-------|-----|--------|-------------|
| D11 Paper Trading | 30 | 70 | 6.25% | **4.38** |
| D12 Backtesting | 25 | 75 | 2.80% | **2.10** |
| D13 Execution Quality | 38 | 62 | 2.00% | **1.24** |
| D2 Options Engine | 93 | 7 | 13.10% | 0.92 |
| D3 Flow Intelligence | 93 | 7 | 10.60% | 0.74 |
| D4 Self-Learning | 95 | 5 | 14.20% | 0.71 |
| D6 Alert Actionability | 93 | 7 | 8.85% | 0.62 |
| D7 Risk Management | 92 | 8 | 7.10% | 0.57 |
| D5 Central Brain | 95 | 5 | 9.30% | 0.47 |
| D1 Proactive Intel | 97 | 3 | 15.40% | 0.46 |
| D8 Data Quality | 90 | 10 | 4.40% | 0.44 |
| D10 UX | 92 | 8 | 2.50% | 0.20 |
| D9 Multi-Agent | 97 | 3 | 3.50% | 0.11 |

**Total weighted gap: ~12.94 points** (87 → ~100)

---

## Phase 1: Paper Trading + Backtesting (D11: 30→80, D12: 25→80) — ~6.0 weighted pts

The biggest bang for buck. These two dimensions are intertwined: paper trading can't be profitable without validated strategies.

### 1A. Root Cause Fix: Signal Quality Gates (D11: 30→55)

**Why paper trading is at 0.2 profit factor**: The system trades signals from sources with 15-18% actual win rates (xtrades, ai_advisor) without discrimination.

| Task | File(s) | What | D11 Impact |
|------|---------|------|-----------|
| Source performance gate | [paper_trade_scheduler.py](backend/services/paper_trade_scheduler.py) | Query per-source profit_factor from `alert_paper_trades`. Auto-disable sources with PF < 0.6 after 10+ closed trades | +5 |
| Technical confirmation filter | [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) | New `_check_technical_confirmation()`: validate signal direction aligns with RSI + 20d SMA + MACD using existing [technical_analysis_service.py](backend/services/technical_analysis_service.py) | +5 |
| Macro regime filter | [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) | New `_check_regime_alignment()`: block long equity in bear/volatile, block CSP in fear, 50% size in cautious. Query regime from [market_regime_agent.py](backend/services/market_regime_agent.py) | +5 |
| Correlation-aware diversification | [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) | New `_check_correlation_limit()`: block >3 open positions in same sector. Query sector from [fmp_client.py](backend/services/fmp_client.py) | +3 |
| Slippage modeling | [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) | Modify `execute_paper_trade`: equity use ask/bid (not mid), options use mid + 25% of spread toward unfavorable. Store `theoretical_price` vs `fill_price` | +5 |
| Attribution + feedback loop | New [paper_trade_attribution.py](backend/services/paper_trade_attribution.py) | On close: decompose P&L into alpha/beta/signal_quality/execution. Feed back into source thresholds. New `paper_trade_attribution` DB table | +7 |

### 1B. Walk-Forward Backtesting Completion (D12: 25→60)

**Key finding**: `advanced_backtest_service.py` has walk-forward + Monte Carlo dataclasses but slippage is never applied, no historical options data, no parameter optimization loop.

| Task | File(s) | What | D12 Impact |
|------|---------|------|-----------|
| Historical options data | [backtest_engine.py](backend/services/backtest_engine.py) | Extend `_fetch_price_data` to query Tradier historical options chains. Cache in new `options_chain_history` table | +10 |
| Apply slippage + commissions | [backtest_engine.py](backend/services/backtest_engine.py) | Config has `slippage_pct: 0.005` but never applied. Apply on both entry and exit. Add spread-based slippage for options | +5 |
| Wire parameter optimizer | [backtest_optimizer.py](backend/services/backtest_optimizer.py) → [backtest.py](backend/routers/backtest.py) | Wire existing optimizer to `POST /api/backtest/optimize`. Add scipy Bayesian optimization | +5 |
| Regime-aware splits | [advanced_backtest_service.py](backend/services/advanced_backtest_service.py) | New `run_regime_aware_backtest()`: classify dates as bull/bear/volatile using VIX+SPY, run separate backtests per regime | +5 |
| Live reconciliation | New [backtest_reconciliation.py](backend/services/backtest_reconciliation.py) | Compare paper trade outcomes to backtest predictions. Flag strategies with >20% divergence. `GET /api/backtest/reconciliation` | +5 |
| Wire earnings backtest | [backtest_engine.py](backend/services/backtest_engine.py) | Integrate existing `earnings_backtest_engine.py` into walk-forward pipeline | +5 |

### 1C. Paper Trade ↔ Backtest Feedback Loop (D11: 55→80, D12: 60→80)

| Task | File(s) | What | Impact |
|------|---------|------|--------|
| Walk-forward validation gate | [paper_trade_scheduler.py](backend/services/paper_trade_scheduler.py) | Before auto-executing: check if strategy has passing walk-forward (robustness > 60). If no backtest exists, queue one. If fails, block trade | D11 +10, D12 +5 |
| Nightly backtest runner | New [backtest_scheduler.py](backend/services/backtest_scheduler.py) | Run walk-forward nightly for active symbols/strategies. Store in `backtest_results` table. Flag degraded strategies | D12 +5 |
| Paper trading dashboard | Frontend enhancement | Equity curve, per-source P&L, signal quality distribution, slippage analysis charts | D11 +5 |

**DB migrations**: `paper_trade_attribution`, `options_chain_history`, `backtest_results`

---

## Phase 2: Execution + Options + Flow (D13: 38→85, D2: 93→100, D3: 93→100) — ~2.9 weighted pts

### 2A. Execution Infrastructure (D13: 38→85)

| Task | File(s) | What | D13 Impact |
|------|---------|------|-----------|
| TWAP/VWAP via Alpaca | New [execution/algo_orders.py](backend/services/execution/algo_orders.py) | `place_twap_order()` splits across time, `place_vwap_order()` weights by volume profile. Wire to [autonomous_executor.py](backend/services/execution/autonomous_executor.py) | +15 |
| TCA service | New [execution/tca_service.py](backend/services/execution/tca_service.py) | Track decision_price → arrival_price → fill_price. Compute implementation shortfall, market impact, delay cost. New `trade_execution_metrics` table. `GET /api/execution/tca` | +15 |
| Price re-quote validation | [autonomous_executor.py](backend/services/execution/autonomous_executor.py) | Before order: re-fetch quote. Reject if moved >1% (equity) or >5% (options) from signal price | +5 |
| Execution analytics | New [execution_analytics.py](backend/routers/execution_analytics.py) | Endpoints: `/analytics`, `/analytics/by-strategy`, `/analytics/fill-quality`. Frontend panel | +7 |
| Smart order type selection | [execution_advisor.py](backend/services/execution_advisor.py) | Spread >1% → limit at mid. Volume <10K → IOC. OI <500 → natural price. Qty >100 → TWAP | +5 |

### 2B. Options Engine Completion (D2: 93→100)

| Task | File(s) | What | D2 Impact |
|------|---------|------|----------|
| IV surface visualization | New [IVSurfaceChart.tsx](frontend/src/components/options/IVSurfaceChart.tsx) | 3D surface (strike x DTE x IV) using existing chain data from `/api/options-unified/chain` | +2 |
| CSP component weight learning | [adaptation_engine.py](src/ada/learning/adaptation_engine.py) | Debug `adapt_component_weights()` at line 613 — likely needs min sample threshold. Ensure scheduler calls it and output goes to `weights.json` + hot-reload | +3 |
| IV mean-reversion scoring | [iv_history_service.py](backend/services/iv_history_service.py) | New `calculate_iv_mean_reversion_score()`: z-score vs 1yr mean. Flag elevated IV as premium-selling opportunity. Inject into CSP scoring | +2 |

### 2C. Flow Intelligence Completion (D3: 93→100)

| Task | File(s) | What | D3 Impact |
|------|---------|------|----------|
| Unusual options → Alert Hub | [unusual_options_scanner.py](backend/services/unusual_options_scanner.py) | New `emit_to_alert_hub()`: vol/OI > 3x creates alert via [alert_hub_service.py](backend/services/alert_hub_service.py). Type: FLOW_UNUSUAL | +2 |
| GEX heatmap frontend | New [GEXHeatmap.tsx](frontend/src/components/flow/GEXHeatmap.tsx) | Heatmap of GEX levels across strikes for SPY/QQQ using existing [gamma_exposure_service.py](backend/services/gamma_exposure_service.py) | +3 |
| SSE inline flow interrupt | [ai_stream.py](backend/routers/ai_stream.py) | High-urgency flow signal (>$1M unusual, >$5M dark pool) injects as `event: alert` SSE between content chunks | +2 |

**DB migrations**: `trade_execution_metrics`

---

## Phase 3: Learning + Alerts + Risk (D4: 95→100, D6: 93→100, D7: 92→100) — ~1.9 weighted pts

### 3A. Self-Learning Completion (D4: 95→100)

| Task | File(s) | What | D4 Impact |
|------|---------|------|----------|
| Weight convergence tracking | [adaptation_engine.py](src/ada/learning/adaptation_engine.py) | Track delta per weight per cycle. If <0.1% change for 5 cycles → "converged". Switch to weekly intervals. New `adaptation_convergence` table | +1 |
| A/B testing activation | [adaptation_engine.py](src/ada/learning/adaptation_engine.py) + [ada_learning_scheduler.py](backend/services/ada_learning_scheduler.py) | Call `seed_csp_confidence_experiment()` from scheduler. Wire `get_active_variant()` into [auto_paper_trade_service.py](backend/services/auto_paper_trade_service.py) CSP threshold selection | +2 |
| Source reliability weighting | [signal_gateway.py](backend/services/signal_gateway.py) | Lookup per-source win rate from `calibration_data`. Apply multiplier: personal (64.7%) → 1.2x, xtrades (18.2%) → 0.5x. Apply to signal confidence | +1 |
| Advisor confidence feedback | [unified_ai_advisor.py](backend/services/unified_ai_advisor.py) | Inject calibration gap into prompt context. Reduce confidence for sources with high predicted-vs-actual gap | +1 |

### 3B. Alert Intelligence Completion (D6: 93→100)

| Task | File(s) | What | D6 Impact |
|------|---------|------|----------|
| Alert performance attribution | New [alert_outcome_service.py](backend/services/alert_outcome_service.py) | Record symbol price at alert time. Check 1d/3d/7d price outcome. Score: profitable move in suggested direction? New `alert_outcomes` table | +3 |
| Alert outcome backtesting | Extend alert analytics | Replay historical alerts against historical prices with 5% SL / 10% PT. Report by source | +2 |
| Dismissal learning | [alert_hub_service.py](backend/services/alert_hub_service.py) | Track dismissal patterns (source, score, symbol). After 50+ dismissals, train logistic regression to predict dismissals → reduce priority score | +2 |

### 3C. Risk Management Completion (D7: 92→100)

| Task | File(s) | What | D7 Impact |
|------|---------|------|----------|
| Real-time VaR monitoring | [advanced_risk_management_service.py](backend/services/advanced_risk_management_service.py) | Scheduled job (15 min): recalc portfolio VaR. Alert Hub alert if VaR > 2% of portfolio | +2 |
| Tail risk hedge recs | New [tail_risk_advisor.py](backend/services/tail_risk_advisor.py) | When CVaR exceeds threshold: recommend SPY puts (delta -0.15 to -0.25), VIX calls. `GET /api/risk/hedging-recommendations` | +2 |
| Extreme scenario replay | [advanced_risk_management_service.py](backend/services/advanced_risk_management_service.py) | Add stress scenarios: 2008 (-38% SPY, VIX 80), COVID (-34%, VIX 82), Dot-com (-49%). Apply scaled shocks to current positions | +2 |
| Regime-aware risk limits | [advanced_risk_management_service.py](backend/services/advanced_risk_management_service.py) | Bull: default limits, Cautious: -25%, Bear: -50%, Fear: halt new positions | +1 |
| Risk → Alert Hub | [advanced_risk_management_service.py](backend/services/advanced_risk_management_service.py) | Emit alerts for VaR breach, circuit breaker trigger, correlation breakdown. Source: "risk_management" | +1 |

**DB migrations**: `adaptation_convergence`, `alert_outcomes`

---

## Phase 4: Brain + Proactive + Data Quality (D5: 95→100, D1: 97→100, D8: 90→100) — ~1.4 weighted pts

### 4A. Central Brain (D5: 95→100)

| Task | File(s) | What | D5 Impact |
|------|---------|------|----------|
| Mount middleware in production | [ada_supervisor.py](src/ada/langgraph/graphs/ada_supervisor.py) | Verify + mount all 4 middleware (context_summarization, dangling_tool_call, loop_detection, token_counting) in supervisor graph | +2 |
| Token budget in SSE | [ai_stream.py](backend/routers/ai_stream.py) | Include `token_usage` summary in final SSE event payload | +1 |
| SSE mid-stream alert injection | [ai_stream.py](backend/routers/ai_stream.py) | Check [avatar_alert_bridge.py](backend/services/avatar_alert_bridge.py) during SSE streaming. Inject critical alerts as `event: alert` between content chunks | +1 |
| Memory retrieval optimization | [episodic.py](src/ada/langgraph/memory/episodic.py) | Add similarity threshold (cosine > 0.7), 30-day TTL, retrieval latency logging | +1 |

### 4B. Proactive Intelligence (D1: 97→100)

| Task | File(s) | What | D1 Impact |
|------|---------|------|----------|
| Attribution → RAG | [trade_attribution_service.py](backend/services/trade_attribution_service.py) | After generating trade lesson, embed via [unified_rag.py](src/rag/unified_rag.py) `add_document()` with type="trade_lesson" metadata | +1 |
| Proactive SSE interrupt | Reuse Phase 4A SSE infrastructure | Extend SSE injection to include proactive portfolio alerts (profit-take, roll, assignment risk) from [proactive_intelligence_engine.py](backend/services/proactive_intelligence_engine.py) | +1 |
| Attribution → advisor confidence | [unified_ai_advisor.py](backend/services/unified_ai_advisor.py) | Query attribution history before recommendations. If user loses on momentum but wins on mean-reversion, weight accordingly in prompt | +1 |

### 4C. Data Quality (D8: 90→100)

| Task | File(s) | What | D8 Impact |
|------|---------|------|----------|
| Centralized data quality service | New [data_quality_service.py](backend/services/data_quality_service.py) | Aggregate from COS [data_quality_prober.py](backend/services/cos/data_quality_prober.py) + per-source freshness. `GET /api/data-quality/dashboard` | +3 |
| SLA enforcement | [data_quality_service.py](backend/services/data_quality_service.py) | Define per-source SLAs (Alpaca: 15s, Tradier: 60s, Robinhood: 5min). Emit Alert Hub alert on violation. Degrade gracefully with staleness warning | +3 |
| Freshness broadcast | WebSocket + new [DataFreshnessIndicator.tsx](frontend/src/components/shared/DataFreshnessIndicator.tsx) | Broadcast `data_freshness` WS event every 60s. Frontend shows green/yellow/red dot per data section | +2 |
| Consolidate validation | Multiple (25+ files) | Extract inline freshness checks into `data_quality_service.validate_freshness()` calls | +2 |

---

## Phase 5: UX + Architecture Polish (D10: 92→100, D9: 97→100) — ~0.3 weighted pts

### 5A. UX Completion (D10: 92→100)

| Task | File(s) | What | D10 Impact |
|------|---------|------|-----------|
| Dark mode toggle | New [ThemeToggle.tsx](frontend/src/components/shared/ThemeToggle.tsx) + [Settings.tsx](frontend/src/pages/Settings.tsx) | Add `class="dark"` toggle on `<html>`. 247+ existing `dark:` classes activate. Persist to localStorage | +2 |
| Command palette | Enhance [KeyboardShortcutsHelp.tsx](frontend/src/components/shared/KeyboardShortcutsHelp.tsx) | Cmd+K palette: navigate pages, search symbols, trigger ADA chat. Reuse Sidebar navigation structure | +2 |
| Onboarding wizard | New [OnboardingWizard.tsx](frontend/src/components/onboarding/OnboardingWizard.tsx) | 4-step flow: Welcome → Connect Robinhood → Set preferences → Quick tour. Show once (localStorage flag) | +2 |
| Accessibility audit | Multiple pages | Run axe-core on key pages. Fix missing alt text, contrast ratios, aria-labels, keyboard nav for modals | +2 |

### 5B. Multi-Agent Architecture (D9: 97→100)

| Task | File(s) | What | D9 Impact |
|------|---------|------|----------|
| Agent unit tests | New files in [backend/tests/](backend/tests/) | Unit tests for all 18 agents (currently only 2 test files). Verify init, basic query, error handling, circuit breaker | +1 |
| Per-agent circuit breakers | [ada_core.py](src/ada/core/ada_core.py) | Add per-agent breakers (currently bus-level only). Failing agent shouldn't trip global breaker | +1 |
| Per-agent health endpoints | [agents.py](backend/routers/agents.py) | `GET /api/agents/{name}/health` → status, last invocation, success rate, breaker state, avg latency | +1 |

---

## Score Projection

| Phase | Dimensions Targeted | Projected Score | Gain |
|-------|-------------------|----------------|------|
| Start | — | **87** | — |
| Phase 1 | D11: 30→80, D12: 25→80 | **93** | +6 |
| Phase 2 | D13: 38→85, D2→100, D3→100 | **95** | +2 |
| Phase 3 | D4→100, D6→100, D7→100 | **97** | +2 |
| Phase 4 | D5→100, D1→100, D8→100 | **98** | +1 |
| Phase 5 | D10→100, D9→100 | **99** | +1 |
| Sustained operation | D11: 80→100, D12: 80→100, D13: 85→100 | **100** | +1 |

**Note**: D11 reaching 100 requires sustained PF > 2.0 over 30+ days of live operation with the improved pipeline. Code changes get to ~80; the remaining 20 points depend on real-world results.

## Dependencies

```
Phase 1B (Backtesting) ──→ Phase 1C (Walk-forward gate for paper trading)
Phase 1A (Signal quality) ──→ Phase 2A (Execution applies to fixed signals)
Phase 2A (TCA) ──→ Phase 4C (Data quality includes execution metrics)
Phase 3A (Learning) ──→ Phase 3B (Alert attribution uses learning data)
Phase 3C (Risk alerts) ──→ Phase 3B (Risk alerts flow to Alert Hub)
Phase 4A (Middleware) ──→ Phase 4B (SSE interrupts use middleware)
```

Phases 2-4 can partially parallelize. Phase 5 has no hard dependencies.

## DB Migrations Required (use `magnus-database` skill)

| Table | Phase | Key Indexes |
|-------|-------|-------------|
| `paper_trade_attribution` | 1 | `trade_id`, `created_at` |
| `options_chain_history` | 1 | `(symbol, date)`, `(symbol, expiration, strike)` |
| `backtest_results` | 1 | `(symbol, strategy)`, `run_date` |
| `trade_execution_metrics` | 2 | `order_id`, `(symbol, created_at)` |
| `alert_outcomes` | 3 | `alert_id`, `(symbol, created_at)` |
| `adaptation_convergence` | 3 | `dimension_name`, `cycle_date` |

## Verification Per Phase

- **Phase 1**: Paper trading PF trending >0.8, walk-forward returns valid results, backtest optimizer wired
- **Phase 2**: TWAP order places via Alpaca sandbox, TCA metrics returned, IV surface renders, GEX heatmap renders
- **Phase 3**: A/B experiment active, alert outcomes tracked at 1d/3d/7d, VaR alerts fire when threshold exceeded
- **Phase 4**: Token usage in SSE, attribution lessons in RAG, data freshness WS events broadcast
- **Phase 5**: Dark mode toggles all pages, Cmd+K opens palette, 18 agent unit tests pass
