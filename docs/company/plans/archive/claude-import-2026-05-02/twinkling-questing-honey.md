# ADA Learning Review #5 — 2026-04-11

```
===============================================================================
                     ADA LEARNING REVIEW — 2026-04-11
===============================================================================

EXECUTIVE SUMMARY
  Overall Health: 70/100 (+2 from last run)
  Biggest Issue: Calibration MAE doubled to 60.8% — confidence system is inverted
  Run #5 | Mode: full | 9 days since Run #4

  Trend: 56 → 62 → 81 → 68 → 70
  Phase: Algorithmic Improvement (started Run #4)

HEALTH MATRIX
  Scheduler:        [GREEN] Running, 55 jobs, 7 learning-specific jobs active
  Container:        [GREEN] Recent learning entries in logs (within 30 min)
  Database:         [GREEN] All endpoints returning data, tables queryable
  Redis:            [GREEN] Connected

  Job Status:
    learning_observation:    Last: 2026-04-11 12:40 ET | Next: scheduled | [OK]
    learning_reflection:     Last: null (not yet today) | Next: 2:38 PM ET    | [OK]
    learning_adaptation:     Last: null (not yet today) | Next: 1:00 PM ET    | [OK]
    learning_validation:     Last: 2026-04-11           | Next: 2026-04-12    | [OK]
    weekly_ml_training:      Last: unknown              | Next: 3:00 PM ET    | [UNKNOWN]
    rag_benchmark:           Not visible in scheduler   | N/A                 | [MISSING]

DATA FLOW STATUS
  Outcome Bridge:     [GREEN] 200 outcomes in 30d (was 200 in run #4, stable)
    - Personal:       907 total signals, 739 acted on, 60.9% WR (was 65.9%)
    - Advisor:        187 total signals, 0 acted on, 49.2% WR (source-perf)
                      BUT source dimension shows 14.0% WR over 559 samples
    - XTrades:        33 total signals, 33 acted on, 18.2% WR (STALE 25+ days)
  Metrics Pipeline:   [GREEN] 8 daily rows in 7d (full coverage Apr 4-11)
  Learning Alerts:    [GREEN] 50 alerts in 30d (19 re-entry, 10 source quality, 21 patterns)
  ML Training:        [RED] Never trained successfully (5 consecutive runs)

ALGORITHM QUALITY SCORECARD
  | Dimension               | Value       | Benchmark | Status | Delta   |
  |-------------------------|-------------|-----------|--------|---------|
  | Brier Score             | null        | < 0.25    | N/A    | --      |
  | Calibration MAE         | 60.8%       | < 10%     | RED    | 30.7→60.8% |
  | Worst Source Win Rate   | 14.0% (adv) | > 40%     | RED    | 13.8→14.0% |
  | Patterns With Evidence  | 15/17       | 100%      | GREEN  | 20/25→15/17 |
  | Weight Adaptation       | 16 cycles   | >=1       | GREEN  | 7→16 cycles |
  | Regression Detected     | YES (-7.1pp)| No        | RED    | No→Yes  |

  CALIBRATION DETAIL (confidence → actual win rate):
    0-20% predicted  → 84.3% actual  (140 samples) — MASSIVELY INVERTED
    20-40% predicted → 62.2% actual  (37 samples)  — INVERTED
    40-60% predicted → 43.1% actual  (153 samples) — Slight overconfidence
    50-60% predicted → 49.8% actual  (281 samples) — DEFAULT BUCKET, near-perfect
    60-80% predicted → 43.3% actual  (104 samples) — SEVERELY overconfident
    90-100% predicted→ 49.0% actual  (50 samples)  — COIN FLIP despite "90%+ confidence"
    100-110% predicted→50.0% actual  (10 samples)  — BUG: confidence >100% shouldn't exist

  WEIGHT ADAPTATION TRAJECTORY (16 new cycles since Run #4):
    recommendation agent: 0.8 → 0.2 (correctly crashing, 0% WR, 13 samples)
    advisor agent:        1.03 → 0.91 (correctly declining, 22% WR, 95 samples)
    personal agent:       1.16 → 1.12 (slight decline, 43.5% WR in rolling window)
    advisor source:       0.71 (down from 1.16 in run #4) — MAJOR correction
    xtrades agent:        0.94 (set Mar 18, no new data to adapt from)

GAP ANALYSIS
  | # | Capability                    | Status  | Severity | Fix                                       |
  |---|-------------------------------|---------|----------|-------------------------------------------|
  | 1 | ML Models Trained             | MISSING | HIGH     | Still blocked: csp_trades empty, no features |
  | 2 | Calibration Populated         | PRESENT | HIGH     | Data exists but QUALITY is catastrophic     |
  | 3 | Adaptation Engine Active      | PRESENT | HIGH     | Very active, 16 cycles, working correctly   |
  | 4 | Alerts Reaching Hub           | PRESENT | MEDIUM   | 50 alerts, robust                           |
  | 5 | Learning Context in Brain     | PRESENT | MEDIUM   | Implemented, stable                         |
  | 6 | Episodic Memory Populated     | PARTIAL | MEDIUM   | patterns.json stale vs DB (17 vs 20+)       |
  | 7 | Paper Trade Auto-Creation     | MISSING | LOW      | Not implemented, deprioritized              |
  | 8 | Frontend Dashboard Has Data   | PRESENT | LOW      | Working, data flowing                       |
  | 9 | All Outcome Sources Active    | PRESENT | HIGH     | All 3 active but advisor/xtrades quality bad|
  | 10| Brier Score Computed          | PARTIAL | MEDIUM   | Cal error computed, formal Brier still null |

TOP 5 PRIORITY ACTIONS (ranked by severity x priority weight)

  1. [CRITICAL] Fix calibration inversion — low-confidence predictions win 84%, high-confidence win 49%
     Root Cause: Most outcomes get default 50% confidence; real predictions at extremes are inverted
     Fix: Add confidence_source flag, exclude default-50% from calibration, or recalibrate the
          confidence assignment pipeline entirely
     Impact: All downstream scoring decisions are wrong  |  Effort: HIGH

  2. [CRITICAL] 100-110% confidence bucket has 10 samples — confidence exceeds 100%
     Root Cause: Bug in confidence assignment or calibration bucket logic
     Fix: Clamp confidence to [0, 1.0] at entry point; investigate where >100% values originate
     Impact: Data integrity  |  Effort: LOW

  3. [HIGH] ML models still never trained after 5 reviews spanning 25 days
     Root Cause: csp_trades table empty, ML pipeline has no training data
     Fix: Either bridge personal_trade_journal → csp_trades, or modify ML pipeline to train
          from learning_outcomes directly (which has 200+ samples)
     Impact: No predictive models, all scoring is rule-based  |  Effort: MEDIUM

  4. [HIGH] Regression detected: 7d WR 23.6% vs 30d WR 30.7% (-7.1pp)
     Root Cause: Broad market sell-off (Apr 7-11) or advisor dragging down overall WR
     Fix: Segment by source — if personal WR stable, it's advisor contamination
     Impact: System may be generating worse recommendations  |  Effort: LOW (diagnosis)

  5. [HIGH] advisor KEEP signal degraded: 70% → 48% accuracy (213 samples)
     Root Cause: Previously identified as best advisor signal type, now at random chance
     Fix: Investigate what changed in advisor recommendation logic. May need to rebuild
          advisor scoring or filter differently
     Impact: Lost the only reliable advisor signal type  |  Effort: MEDIUM

WHAT CHANGED SINCE LAST REVIEW (Run #4 → Run #5)

  IMPROVEMENTS:
  + Adaptation engine highly active: 16 new cycles (was 7 total through run #4)
  + Recommendation agent correctly penalized: weight 0.8 → 0.2 for persistent 0% WR
  + Advisor SOURCE weight corrected: 1.16 → 0.71 (massive fix from run #4's contradiction)
  + Metrics pipeline consistently producing daily rows (8/7 days)
  + New pattern discoveries: OKLO (87% WR, 15 trades), KLAR (73%), RBLX growing (76%)
  + Data volume continues growing: 1127 total signals across all sources

  REGRESSIONS:
  - Calibration MAE DOUBLED: 30.7% → 60.8% (more data = more truth, but it's ugly)
  - Personal WR declined: 65.9% → 60.9% (still strong but down 5pp)
  - Advisor KEEP signal collapsed: 70% → 48% (was the last reliable advisor signal)
  - Regression detected: -7.1pp in 7-day window
  - XTrades COMPLETELY STALE: 33 signals unchanged for 25+ days
  - ML models still never trained (run streak: 5)
  - Weight overrides INACTIVE (were active runs 2-3, now 0 overrides)
  - Confidence >100% bug discovered (10 samples in 100-110% bucket)

  NEW FINDINGS:
  - Advisor WR discrepancy: source-performance says 49.2% but source dimension says 14.0%
    → Different measurement windows/methods producing contradictory signals
  - Advisor signal type breakdown: KEEP=48%, ROLL=50%, HOLD=50%, CLOSE=50%, SELL=50%
    → ALL advisor signal types regressed to ~50% (random chance). Advisor is broken.
  - SMCI survivorship bias confirmed: 100% → 60% WR as sample grows (30→62 trades)
  - Overlapping calibration buckets (40-60 AND 50-60, 80-100 AND 80-90 AND 90-100)
    → Calibration endpoint has a data quality bug producing overlapping ranges

AUTO-TRIGGERED
  - No auto-triggers (run without --fix flag)

SELF-LEARNING NOTES
  - Priority adjustments needed:
    * calibration_quality: INCREASE from 0.15 → 0.18 (worst dimension, doubled MAE)
    * ml_models_trained: DECREASE from 0.13 → 0.11 (5 consecutive misses, structural blocker)
    * paper_trade_auto: KEEP at 0.00 (permanently deprioritized)
    * NEW: advisor_quality_crisis: 0.12 (all signal types at random, needs dedicated tracking)
  - Runbook updates needed:
    * NEW: Confidence >100% bug — investigate origin and add clamp
    * NEW: Overlapping calibration buckets — endpoint producing duplicate bucket ranges
    * NEW: Advisor all-signal-types regression to 50% — fundamental advisor quality issue
  - Score trend: 56 → 62 → 81 → 68 → 70 (recovering +2 from run #4 drop, but flat)
    Infrastructure phase completed (runs 1-3). Algorithmic improvement phase stalled.
    The system correctly adapts weights (recommendation→0.2, advisor→0.91) but the
    underlying confidence calibration makes all scoring unreliable.
===============================================================================
```

## Knowledge File Updates Needed

After approval, these knowledge files should be updated:

### 1. calibration.json — Update buckets
- New buckets: 50-60%, 70-80%, 80-90%, 90-100%, 100-110%
- Mean absolute error: 60.863 (was 30.7)
- Add history entry for 2026-04-11
- Source calibration: advisor now shows 49.2% WR with 187 samples (was 13.8%/483)

### 2. patterns.json — Sync with DB
New patterns to add from DB:
- OKLO: 87% WR, 15 trades (new re-entry signal)
- KLAR: 73% WR (new)
- advisor KEEP degraded: 70% → 48% (update existing p008)
- advisor ADD: 55% accuracy, 10 predictions (new)
- RBLX: 76% WR, 21 trades (update, was 71%/7)
- SMCI: updating from 57% to 60% WR, 62 trades (growing sample)
- ONDG: 18% WR (new poor performer)
- recommendation agent: still 0% WR, weight now 0.2 (update p017)

### 3. weights.json — Already auto-updating
Adaptation history has 16 entries since run #4. File is current through 2026-04-10.

### 4. LEARNINGS.md — Add Run #5 section
- Document advisor all-signal-type regression
- Document calibration doubling
- Document new symbols (OKLO, KLAR)
- Document recommendation agent approaching zero

### 5. review_history.json — Append Run #5 entry

### 6. priorities.json — Update weights

### 7. runbook.md — Add 3 new issues

## Verification

To verify these findings, run:
```bash
# Confirm regression
curl -s http://localhost:8006/api/learning/regression-check | python -m json.tool

# Confirm calibration state
curl -s http://localhost:8006/api/learning/calibration | python -m json.tool

# Check if ML training has ever run
docker logs ada-backend --since 720h 2>&1 | grep -c "ml_training.*complete"

# Verify advisor signal breakdown
curl -s http://localhost:8006/api/learning/source-performance | python -m json.tool
```
