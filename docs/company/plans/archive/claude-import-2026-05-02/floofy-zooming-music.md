# Plan: Create `platform-auditor` Skill — Comprehensive ADA Feature Audit

## Context

ADA has 3 existing audit skills that leave a critical blind spot:

| Skill | What It Grades | Blind Spot |
|-------|---------------|------------|
| `advisor-audit` | System-level advisory intelligence (13 dimensions) | Doesn't audit individual pages, sub-tabs, or deep links |
| `feature-reviewer` | Code quality per feature (5 dimensions) | Doesn't check if features actually work, return real data, or integrate |
| `learning-review` | Self-learning subsystem health | Only covers learning, not the full platform |

**The gap**: No skill inventories every feature/page/deep-link, grades its functional quality, detects dead features, finds duplication, or benchmarks against competitors. The user wants a single skill that audits the ENTIRE system holistically.

**The platform surface**: 82 active routes, 51 sidebar items, 240 mounted routers, 427 services, 25 scheduled jobs.

---

## What We're Building

A new skill at `.claude/skills/platform-auditor/` that:

1. **Inventories all 37 auditable features** (organized by sidebar section: HOME, HUBS, TOOLS, SYSTEM)
2. **Grades each feature 0-100** across 6 dimensions (functional completeness, data quality, integration, UX, optimization, competitive edge)
3. **Runs system coherence checks** (data flow integrity, API consistency, UX consistency, duplication detection, dead feature detection)
4. **Self-improves** via knowledge files that track trends, evolve weights, and learn from user actions
5. **Researches competitors** (TradingView, Tastytrade, Unusual Whales, OptionStrat, Mezzi) per feature

---

## Files to Create

### 1. `.claude/skills/platform-auditor/SKILL.md`
The main skill definition with:
- YAML frontmatter (triggers: "platform audit", "full audit", "feature audit", "audit all features")
- 37-feature catalog organized by sidebar section
- 6-dimension grading rubric with scoring matrices
- 5 system coherence checks
- Self-improvement loop (weight evolution, competitive baseline updates, pattern learning)
- Modes: `--full` (default), `--quick` (skip unchanged), `--section {name}`, `--feature {name}`, `--coherence`, `--competitive`
- Safety rules (read-only, timeout curls, batch API calls)

### 2. `.claude/skills/platform-auditor/knowledge/feature_catalog.json`
Pre-populated catalog of all 37 features with:
- Route, page file, routers, services, API prefix
- Sub-tabs and deep links
- Importance weight (1.5x for core, 1.2x for key, 1.0x for standard, 0.7x for system/tools)
- Competitive reference platform

### 3. `.claude/skills/platform-auditor/knowledge/dimension_weights.json`
Default 6-dimension weights:
- Functional Completeness: 25%
- Data Quality: 20%
- Integration: 20%
- UX/Performance: 15%
- Optimization: 10%
- Competitive Edge: 10%

### 4. `.claude/skills/platform-auditor/knowledge/competitive_baselines.json`
5 competitor platforms (TradingView, Tastytrade, Unusual Whales, OptionStrat, Mezzi) with per-feature benchmarks.

### 5. `.claude/skills/platform-auditor/knowledge/audit_history.json`
Empty `[]` — populated on first run.

### 6. `.claude/skills/platform-auditor/knowledge/duplication_registry.json`
Empty `{"version": 1, "pairs": []}` — populated when duplication detected.

### 7. `.claude/skills/platform-auditor/knowledge/dead_features.json`
Empty `{"version": 1, "features": []}` — populated when dead features detected.

### 8. `.claude/skills/platform-auditor/knowledge/improvement_patterns.md`
Template with section headers for tracking high-impact patterns, ignored recommendations, and false positives.

---

## The 37 Auditable Features

### HOME (2)
| # | Feature | Route | Importance |
|---|---------|-------|-----------|
| 1 | Dashboard | `/` | 1.5x |
| 2 | Ask ADA | `/ask-ada` | 1.5x |

### HUBS (22)
| # | Feature | Route | Importance |
|---|---------|-------|-----------|
| 3 | Trade Planner | `/trade-planner` | 1.5x |
| 4 | Portfolio | `/portfolio` | 1.5x |
| 5 | Trade Intelligence | `/trade-intelligence` | 1.0x |
| 6 | Advisor Track Record | `/advisor-track-record` | 1.0x |
| 7 | Paper Trading | `/paper-trading` | 1.0x |
| 8 | Alert Hub | `/alert-hub` | 1.2x |
| 9 | Rules | `/rules` | 1.0x |
| 10 | News | `/news` | 1.0x |
| 11 | Premiums (Scanner) | `/scanner` | 1.2x |
| 12 | Earnings Intelligence | `/earnings-intelligence` | 1.2x |
| 13 | IPO Calendar | `/ipo-hub` | 1.0x |
| 14 | XTrades | `/xtrades` | 1.2x |
| 15 | Whale Intelligence | `/whale-intelligence` | 1.0x |
| 16 | Options Intelligence | `/options-intelligence` | 1.0x |
| 17 | Chart Analysis | `/chart-analysis` | 1.2x |
| 18 | Markets | `/markets` | 1.0x |
| 19 | ETF Hub | `/etf-hub` | 1.0x |
| 20 | Prediction Markets | `/prediction-markets` | 1.0x |
| 21 | Quant Lab | `/quant-lab` | 1.0x |
| 22 | Stock Detail | `/stocks/detail/:symbol` | 1.2x |
| 23 | Strategy Hub | `/strategy-hub` | 1.0x |
| 24 | Research | `/research` | 1.0x |

### TOOLS (6)
| # | Feature | Route | Importance |
|---|---------|-------|-----------|
| 25 | Comps Analysis | `/comps-analysis` | 0.7x |
| 26 | DCF Valuation | `/dcf-valuation` | 0.7x |
| 27 | Vol Analysis | `/vol-analysis` | 0.7x |
| 28 | Rebalancing | `/rebalancing` | 0.7x |
| 29 | Tax Harvesting | `/tlh-workflow` | 0.7x |
| 30 | Screener | `/fundamental-screens` | 0.7x |

### SYSTEM (7)
| # | Feature | Route | Importance |
|---|---------|-------|-----------|
| 31 | System Hub | `/system-hub` | 0.7x |
| 32 | Sprint Manager | `/sprint-manager` | 0.7x |
| 33 | Agent Dashboard | `/agent-dashboard` | 0.7x |
| 34 | QA Dashboard | `/qa` | 0.7x |
| 35 | Feature Quality | `/feature-quality` | 0.7x |
| 36 | Documentation | `/documentation` | 0.7x |
| 37 | Settings | `/settings` | 0.7x |

---

## 6-Dimension Grading (Per Feature)

### D1: Functional Completeness (25%)
- Page loads (200, not 500/404)
- All sub-tabs accessible and rendering content
- Core CRUD operations respond
- No "Coming Soon", "TODO", "placeholder" content
- Graceful empty states

### D2: Data Quality (20%)
- API returns real data (not empty arrays, not nulls)
- Data freshness (timestamps within expected cycle)
- No hardcoded demo/sample data
- Expected fields populated

### D3: Integration (20%)
- Inbound links from other features
- Outbound links to related features
- Signal flow to downstream consumers
- Deep links functional
- Shared data consistency across views

### D4: UX/Performance (15%)
- Loading states (skeleton/spinner)
- Error handling (user-friendly, not raw errors)
- Responsive design
- Empty state handling
- Renders within 3 seconds

### D5: Optimization (10%)
- No capability duplication with other features
- No dead code / unused imports
- Appropriate complexity
- Lean bundle impact

### D6: Competitive Edge (10%)
- Feature parity with best-in-class competitor
- Unique AI/learning advantage
- Gap severity assessment

---

## System Coherence Checks

1. **Data Flow Integrity**: Signal Generation -> Analysis -> Recommendation -> Execution -> Learning
2. **API Consistency**: Response envelope, error format, naming conventions, pagination
3. **UX Consistency**: Loading patterns, empty states, error display, tab patterns
4. **Duplication Detection**: Pairwise comparison of overlapping features
5. **Dead Feature Detection**: Pages with zero inbound nav, empty data, stale modification dates

---

## Issues Already Discovered (to fix during implementation)

| Issue | Impact | Fix |
|-------|--------|-----|
| `brain.py` router not mounted in main.py | `/api/brain` endpoints unreachable | Mount or delete |
| `cos.py` router not mounted in main.py | `/api/cos` endpoints unreachable | Mount or delete |
| `strategy.py` dual registration | Confusing `/api/strategy` + `/api/strategies` | Consolidate |
| `alert_intelligence.py` deprecated but present | Dead code | Remove after grace period |

---

## Execution Order

1. Create skill directory and SKILL.md
2. Create all 7 knowledge files (catalog pre-populated, others empty/default)
3. Run initial baseline audit (`/platform-auditor`) to establish scores
4. Fix the 4 discovered issues (orphaned routers, dual registration, deprecated router)
5. Re-run to verify improvements

---

## Verification

After creating the skill:
1. Confirm SKILL.md loads as a valid skill (check triggers work)
2. Confirm all knowledge files parse as valid JSON/markdown
3. Run `/platform-auditor --quick` on a single feature to validate the grading flow
4. Run full audit and verify output format matches the report template
5. Verify knowledge files are populated after first run

---

## Key Source Files Referenced

- [App.tsx](frontend/src/App.tsx) — All 167 route definitions
- [Sidebar.tsx](frontend/src/components/Sidebar.tsx) — 51 sidebar navigation items
- [main.py](backend/main.py) — 240 router mount registrations
- [advisor-audit SKILL.md](.claude/skills/advisor-audit/SKILL.md) — Pattern for skill structure
- [competitive_baseline.json](.claude/skills/advisor-audit/knowledge/competitive_baseline.json) — Import competitive data
- [MASTER_SCORECARD.md](.claude/memory/quality/MASTER_SCORECARD.md) — Existing code quality grades
