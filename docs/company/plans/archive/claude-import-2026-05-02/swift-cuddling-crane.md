# Platform-Auditor: Comprehensive ADA Platform Quality Audit

## Context

Running a full audit of the ADA platform's 37+ features across 6 quality dimensions. This is audit run #8, following a degraded run #7 on 2026-04-21 (platform grade: 81.8/82.9) where Ollama was offline.

**Key factors for this audit:**
- **9 days** since last audit with **20+ commits** including major weekly planner fixes, learning system improvements, and ADA theta advisor enhancements
- **Backend healthy** (2.0.0, timestamp working) but **Ollama still offline** - LLM routing falls back to minimax-m2.7 cloud
- **Previous issues to verify**: Prediction Markets (broken 7 audits), News/ETF regressions from run 6, comps/dcf data pipelines

**Expected improvements from recent commits:**
- Trade Planner: comprehensive parsing fixes, LLM integration modernization
- Learning system: confidence bias elimination
- Performance indicators: cross-project average matching improvements
- Weekly planning: parsing status consistency fixes

## Implementation Plan

### Phase 1: State Loading & Change Detection (3-5 min)

1. **Load previous state** from knowledge files:
   - `audit_history.json` - 7 previous runs, latest degraded due to Ollama
   - `feature_catalog.json` - 37 features, last updated 2026-04-12  
   - `dimension_weights.json` - default weights (D1:25%, D2:20%, D3:20%, D4:15%, D5:10%, D6:10%)
   - `competitive_baselines.json`, `duplication_registry.json`, `dead_features.json`

2. **Feature auto-discovery**:
   - Read `frontend/src/App.tsx` - extract all route definitions
   - Compare to catalog, flag any NEW routes not documented
   - Read `frontend/src/components/Sidebar.tsx` - verify 36 sidebar items match catalog

3. **Change impact mapping**:
   - Map 20+ commits since 2026-04-21 to affected features using `feature_catalog.json`
   - Priority list: Trade Planner, Learning features, Portfolio (theta advisor), Performance dashboards

### Phase 2: Backend Pre-Warming (2-3 min)

**Critical**: Prevent false D2 failures from cold-start timeouts (lesson from run 3)

1. **Warm critical services**:
   ```bash
   curl -s --max-time 15 http://localhost:8006/api/dashboard/summary
   curl -s --max-time 15 http://localhost:8006/api/portfolio  
   curl -s --max-time 15 http://localhost:8006/api/market
   ```
   
2. **Wait 5 seconds** for async workers to stabilize

3. **LLM degradation assessment**:
   - Test `/api/ada/chat` and `/api/langgraph` endpoints
   - Flag features requiring local LLM vs cloud-fallback capable

### Phase 3: Feature Audit - Priority Order (15-20 min)

**Audit order**: HUBS (highest impact) → HOME → TOOLS → SYSTEM

#### Feature Processing (per feature):

**D1 - Functional Completeness (25%)**
- Page loads (not 404/500/blank)
- All sub-tabs render content  
- Primary API endpoints return 200 status
- Graceful empty states vs crashes
- Placeholder detection: grep for "Coming Soon|TODO|placeholder|Lorem|Not implemented"

**D2 - Data Quality (20%)**
- Real data volume check: `jq 'length'` on API responses
- Freshness: timestamp recency within expected cycles
- Null-heavy detection: `jq '[.. | nulls] | length'`
- No dummy data: grep for "demo|example|test_|sample"

**D3 - Integration (20%)**  
- Inbound links: `grep -rl "to=\"{route}"` count
- Outbound navigation: `grep -c "to=\"/|navigate("` in page file
- Signal flow: cross-service imports using `grep -rl "{api_prefix}"`
- Deep link functionality verification

**D4 - UX/Performance (15%)**
- Loading states: `grep -c "isPending|Skeleton|Spinner"`
- Error boundaries: `grep -c "ErrorBoundary|isError"`  
- Responsive: `grep -c "md:|lg:|sm:|flex-col"`
- Performance: sub-3s page render timing

**D5 - Code Quality + Optimization (10%)**
Frontend optimization:
- Dead code: unreferenced components
- Complexity: >500 LOC flags
- Bundle impact: large unused imports

Backend quality:
- `grep -c "except:"` - bare exceptions (-3 pts each)
- `grep -c "TODO|FIXME|HACK"` (-2 pts each)  
- `grep -c "print("` - should use logger (-5 pts each)
- Functions >100 LOC detection (-5 pts each)

**D6 - Competitive Edge (10%)**
- Compare vs `competitive_baselines.json`
- Feature parity assessment
- Unique AI advantage identification

#### High Priority Features (1.5x importance weight):
- **Dashboard** (recent commits impact market overview)
- **Portfolio** (theta advisor improvements) 
- **Trade Planner** (major parsing/LLM fixes)
- **Ask ADA** (LLM routing changes)

#### Vulnerable Features (likely regression):
- **Prediction Markets** (broken 7 audits, service disabled)
- **News** (NameError regressions in runs 6-7)
- **ETF Hub** (404 regressions, run 6)
- **Comps Analysis** (data pipeline issues)
- **DCF Valuation** (data pipeline issues)

### Phase 4: System Coherence Analysis (5-8 min)

1. **Data Flow Integrity**:
   Trace signal pipeline: Scanner/XTrades/Flow → Analysis/Conviction → Recommendations/Alerts → Execution → Learning
   
2. **API Consistency**:
   Sample 10 endpoints for response format, error patterns, naming conventions
   
3. **UX Consistency**:  
   Check loading/error/empty state patterns across 5+ pages
   
4. **Duplication Detection**:
   Pairwise comparison of overlapping capabilities:
   - Scanner vs Options Intelligence
   - Alert Hub vs Rules  
   - Dashboard vs Trade Planner
   - Trade Intelligence vs Advisor Track Record
   
5. **Dead Feature Detection**:
   Features with zero inbound navigation AND score <50 AND no changes in 30+ days

### Phase 5: Report Generation & Knowledge Update (5-10 min)

1. **Platform Scorecard**:
   - Overall grade (simple + weighted average)
   - Feature ranking (worst-first for improvement focus)
   - Dimension breakdown per feature
   - Grade distribution histogram
   - Trend analysis vs run 7

2. **High-Impact Improvement List**:
   Ranked by `(100 - score) * importance_weight`
   - Specific actionable fixes
   - Effort estimates (S/M/L)
   - Expected point gains

3. **Issue Resolution Status**:
   - P0/P1 issues from previous runs
   - New regressions detected
   - Recovery confirmations

4. **Knowledge File Updates**:
   - Append to `audit_history.json` (prune to last 20 runs)
   - Update `feature_catalog.json` with any discoveries
   - Evolve `dimension_weights.json` based on user action patterns
   - Update duplication/dead feature registries

### Phase 6: Self-Improvement Analysis (2-3 min)

- Compare trends vs run 7 (degraded) and run 6 (healthy baseline)
- Identify which commit types drove biggest score improvements  
- Update improvement patterns with new learnings
- Flag any audit methodology improvements for next run

## Expected Outcomes

**Likely Platform Grade**: 82-85 (improvement over run 7 due to trade planner fixes, but still degraded due to Ollama offline)

**Key Improvements Expected**:
- Trade Planner: +3-5 points (parsing fixes, LLM modernization)
- Learning features: +2-4 points (confidence bias elimination)  
- Portfolio: +1-3 points (theta advisor enhancements)

**Persistent Issues**:
- Prediction Markets: likely still broken (service disabled)
- Comps/DCF: may still have data pipeline issues
- Any LLM-dependent features: degraded performance without Ollama

**Success Criteria**:
- Complete audit of all 37 features within 25-30 minutes
- Accurate trend analysis vs previous runs
- Actionable improvement recommendations with effort estimates
- Updated knowledge base ready for future audits
- Platform grade reflects actual functional quality, not just code changes

## Verification Plan

**Audit Quality Checks**:
- Verify API response times <10s (prevent false D2 failures)
- Cross-check feature scores against manual spot tests of top issues
- Confirm trend analysis makes sense given known commits
- Validate new feature discoveries against actual route definitions

**Knowledge Consistency**:
- Feature catalog accuracy vs App.tsx routes
- Improvement patterns align with historical impact data
- Dimension weights evolution reflects user priority patterns