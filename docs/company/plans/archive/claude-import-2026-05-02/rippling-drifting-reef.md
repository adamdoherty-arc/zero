# Platform Audit Run #3 — Live Verification

## Context

This is the **3rd audit run today**. Run 1 was a full audit (platform grade 76.5). Run 2 was a code-fix pass that applied 7 waves of improvements but **never verified against the live backend** (estimated grade 87.5). This run's purpose is to **live-verify** all improvements and establish accurate baseline scores.

All Docker containers are confirmed running: backend (port 8006, up 14 min), frontend (port 5420), postgres, redis, qdrant, neo4j, pgbouncer.

## Approach: Parallel Batch Verification

Execute the audit in **5 parallel batches** using Task subagents, then synthesize results in the main conversation.

### Batch 1: HOME + Top HUBS (7 features, highest importance)
**Features:** Dashboard, Ask ADA, Trade Planner, Portfolio, Alert Hub, XTrades, Stock Detail

For each feature:
1. `curl -s --max-time 10 http://localhost:8006{primary_endpoint}` — check HTTP 200, data present
2. Grep page file for: `TODO|placeholder|Coming Soon|hardcoded`
3. Check loading states: `isPending|Skeleton|animate-spin`
4. Check error handling: `isError|ErrorBoundary|error &&`
5. Check cross-links: `navigate|to="|Link to`
6. Check component structure: monolithic vs split (lazy imports)

### Batch 2: Mid-tier HUBS (10 features)
**Features:** Earnings Intel, Premiums Scanner, Chart Analysis, Whale Intelligence, Options Intel, Markets, ETF Hub, Prediction Markets, IPO Calendar, News Hub

Same 6-point check per feature.

### Batch 3: Learning + Execution HUBS (5 features)
**Features:** Trade Intelligence, Advisor Track Record, Paper Trading, Quant Lab, Rules

Same 6-point check per feature.

### Batch 4: TOOLS (6 features)
**Features:** Comps Analysis, DCF Valuation, Vol Analysis, Rebalancing, Tax Harvesting, Screener

Same 6-point check, plus verify cross-links to Stock Detail tabs (added in Run 2 fix pass).

### Batch 5: SYSTEM (9 features)
**Features:** System Hub, Sprint Manager, Agent Dashboard, Orchestration Manager, QA Dashboard, Feature Quality, Enhancement, Documentation, Settings

Same 6-point check, plus verify Run 2 fixes (Orchestration Manager should no longer be D, Agent Dashboard should have real WebSocket data, Documentation should use axiosInstance).

### Post-Batch: System Coherence Checks

After all 5 batches complete:

1. **Data Flow Integrity** — Trace signal pipeline: Scanner/XTrades → AI Advisor → Trade Planner → Paper Trading → Learning. Verify each stage's output is consumed by the next via grep for cross-service API calls.

2. **API Consistency** — Sample 10 endpoints for response envelope format, error format, naming conventions.

3. **UX Consistency** — Verify consistent loading/error/empty state patterns across 5+ pages.

4. **Duplication Check** — Re-assess known pairs: Quant Lab vs Risk Dashboard (40% overlap), Alert Rules vs Smart Rules (25% overlap).

5. **Dead Feature Check** — Verify Run 2 false positive corrections (ETF Hub, Feature Quality now confirmed working).

### Scoring

For each feature, score 6 dimensions using dimension_weights.json:
- D1: Functional Completeness (25%) — page loads, sub-tabs, core actions, empty states
- D2: Data Quality (20%) — real data from APIs, freshness, completeness
- D3: Integration (20%) — inbound/outbound links, signal flow, deep links
- D4: UX/Performance (15%) — loading states, error handling, responsive
- D5: Optimization (10%) — code size, duplication, component extraction
- D6: Competitive Edge (10%) — vs competitive_baselines.json benchmarks

Final: `feature_score = sum(dimension_score * dimension_weight)`

### Report Generation

Write full audit report including:
- Platform-wide grade (simple avg + importance-weighted avg)
- Per-feature scorecard (ranked worst-first)
- Top 10 highest-impact improvements
- Duplication report
- Dead feature report
- Competitive gap analysis
- System coherence summary
- Comparison to Run 1 and Run 2

### Knowledge File Updates

Update these files in `.claude/skills/platform-auditor/knowledge/`:
- `audit_history.json` — Append Run 3 results
- `dead_features.json` — Update resolved false positives
- `dimension_weights.json` — Evolve weights based on user actions
- `improvement_patterns.md` — Document which fixes had impact

## Key Files to Modify

| File | Purpose |
|------|---------|
| `.claude/skills/platform-auditor/knowledge/audit_history.json` | Append Run 3 full results |
| `.claude/skills/platform-auditor/knowledge/dead_features.json` | Update false positive corrections |
| `.claude/skills/platform-auditor/knowledge/dimension_weights.json` | Evolve weights |
| `.claude/skills/platform-auditor/knowledge/improvement_patterns.md` | Impact documentation |

## Expected Outcomes from Exploration

Based on the 3 exploration agents, preliminary findings suggest:
- **Lowest-scoring features improved dramatically**: Orchestration Manager 69→~88, Enhancement 75→~88, Rules 78→~91, Agent Dashboard 78→~93
- **High-importance features are strong**: Dashboard A+, Portfolio A+, XTrades A, Trade Planner A
- **Remaining weak spots**: UnifiedOptionsHub still monolithic (1356 LOC), StockDetailPage large (1592 LOC), AlertHub hook exports in page file
- **Platform grade expected**: ~88-91 (up from 87.5 estimated in Run 2)

## Verification

After generating the report:
1. Spot-check 5 API endpoints with curl to confirm scores
2. Compare Run 3 scores to Run 1 and Run 2 to validate trends
3. Ensure no feature regressed below its Run 2 score without explanation
