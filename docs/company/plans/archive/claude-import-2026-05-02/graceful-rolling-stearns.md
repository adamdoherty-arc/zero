# Plan: Fix Match Page Bugs + Build Platform Auditor Skill

## Context
The Matches page has two bugs: (1) match cards show "NaN%" for Skills/Experience/Salary scores due to field name mismatches with the API, and (2) match detail pages are stuck on "Loading match details..." for ALL matches. Additionally, a comprehensive per-feature platform auditor skill is needed, modeled after ADA's `platform-auditor` and Legion's `legion-platform-auditor`.

---

## Part 1: Fix Match Page Bugs

### Bug A: NaN% on Match Cards (CONFIRMED)

**Root cause**: `Matches.jsx` references `match.skill_match`, `match.experience_match`, `match.salary_match`, and `match.in_queue` but the backend `MatchResponse` schema returns `skill_match_score`, `experience_match_score`, `salary_match_score`, and `in_application_queue`.

**File**: [Matches.jsx](frontend/src/pages/Matches.jsx)

**Changes** (10 replacements via `replace_all`):
- `match.skill_match` -> `match.skill_match_score` (lines 171, 174, 177)
- `match.experience_match` -> `match.experience_match_score` (lines 186, 189, 192)
- `match.salary_match` -> `match.salary_match_score` (lines 201, 204, 207)
- `match.in_queue` -> `match.in_application_queue` (line 223)

### Bug B: Match Detail Page Stuck Loading

**Root cause**: Likely a Pydantic serialization error on the backend detail endpoint. The `ResumeInfo` schema requires `file_name: str` (non-null) but resumes can have null `file_name`. This causes a 500 error, and the page header renders fallback values ("0" score, "Match Details" title) while the tab content stays stuck on loading.

**Diagnostic step**: `curl http://localhost:8001/api/matches/<id>/detail -H "X-User-Id: 1"` to confirm the 500 error.

**Backend fix** - [matches.py](backend/app/api/matches.py):
- Line 123: `file_name: str` -> `file_name: Optional[str] = None`
- Line 124: `is_primary: bool` -> `is_primary: bool = False`
- Line 93: `ai_enriched: bool` -> `ai_enriched: bool = False`

**Frontend fix** - [MatchDetail.jsx](frontend/src/pages/MatchDetail.jsx):
- Add early returns for `isLoading` and `error` states at line 100 (before the header renders) so the page shows a clean full-page loading/error state instead of a half-rendered page with fallback values.

### Verification
1. Rebuild frontend + backend containers
2. Visit `/matches` - verify scores show percentages not NaN%
3. Click any match - verify detail page loads with full data
4. `curl /api/matches/<id>/detail -H "X-User-Id: 1"` returns 200 with valid JSON

---

## Part 2: Build fortress-platform-auditor Skill

### What it does
Per-feature quality audit grading ~28 features across 6 dimensions (Functional Completeness, Data Quality, Integration, UX/Performance, Code Quality, Test Coverage), with system coherence checks, auto-remediation, and adaptive learning. Modeled after ADA's `platform-auditor` and Legion's `legion-platform-auditor`.

### How it differs from existing `fortress-audit`
| Aspect | fortress-audit (keep) | fortress-platform-auditor (new) |
|--------|----------------------|-------------------------------|
| Scope | 11 abstract dimensions | ~28 features x 6 dimensions |
| Scoring | 12 checks per dimension | 6 dimensions per feature |
| Coherence | None | 5 system coherence checks |
| Auto-fix | Report only | Fixes S/M effort issues in-session |
| Discovery | Hardcoded file lists | Auto-discovers from routes + routers |

### New files to create

```
.claude/skills/fortress-platform-auditor/
  SKILL.md                          # ~500 lines, full execution instructions
  knowledge/
    feature_catalog.json            # ~28 features mapped to routes/routers/hooks/APIs
    audit_history.json              # Empty initial array (20-run cap)
    dimension_weights.json          # Default 6-dimension weights
    competitive_baselines.json      # Per-feature competitor benchmarks
    dead_features.json              # Empty initial
    duplication_registry.json       # Known acceptable overlaps
    code_quality_baseline.json      # Anti-pattern counts
    improvement_patterns.md         # Header only
```

### Feature catalog (28 features, 5 tiers)

**Core (1.5x)**: Dashboard, Jobs, Matches
**Important (1.2x)**: Applications, Resume, Cover Letters, Favorites, Deep Evaluation
**Standard (1.0x)**: Target Companies, Contacts, Story Bank, Negotiation, Career Strategy, Personas, LinkedIn, Knowledge, Analytics, Skills, Projects
**System (0.7x)**: Orchestration, Profile, Sources, Jor-El (AI), Sprints
**Backend-only (0.5x)**: Gmail, Companies, Enhancement, Search Templates, Compensation, Metrics

### 6 Dimensions per feature
1. **Functional Completeness** (25%) - Page loads, CRUD works, endpoints reachable
2. **Data Quality** (20%) - Real data, no null renders, no NaN, no "undefined"
3. **Integration** (20%) - Inbound/outbound links, signal flow, shared components
4. **UX/Performance** (15%) - Loading states, error handling, empty states, responsive
5. **Code Quality** (10%) - Correct field names, project patterns, no anti-patterns
6. **Test Coverage** (10%) - Backend test exists, meaningful tests, correct fixtures

### 5 System coherence checks
1. **Data Flow**: Job -> Match -> Application -> Follow-up -> Outcome -> Learning
2. **API Consistency**: Envelope format, AppException, pagination, CurrentUserId
3. **UX Consistency**: Loading/error/empty patterns across all pages
4. **Duplication Detection**: Feature pairs with overlapping functionality
5. **Dead Feature Detection**: No inbound links + errors + stale + low score

### Auto-remediation rules
- **S/M effort** (< 30 min, < 3 files): Fix immediately, verify, commit atomically
- **L effort**: Add as sprint recommendations with estimated impact
- Never skip fixes; verify before committing; update baselines after

### 10-step execution flow
1. Load previous state from knowledge files
2. Auto-discover features from App.jsx routes + main.py routers + api.js services
3. Per-feature evaluation (6 dimensions each)
4. System coherence checks (5 checks)
5. Calculate platform score (weighted average + coherence bonus)
6. Compare to previous run (per-feature deltas, regressions)
7. Auto-remediation (S/M effort fixes)
8. Generate sprint recommendations (top 5 by weighted gap)
9. Update knowledge files (cap history at 20 runs)
10. Output formatted report

### Verification
- Run `/fortress-platform-auditor`
- Verify it discovers all features from App.jsx/main.py
- Verify each feature gets scored across 6 dimensions
- Verify coherence checks run
- Verify knowledge files are written
- Verify report is formatted correctly
