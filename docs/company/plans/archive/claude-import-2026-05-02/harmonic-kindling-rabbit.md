# Analysis: code-review-graph vs ADA's Existing Capabilities

## Context

**Repo**: [tirth8205/code-review-graph](https://github.com/tirth8205/code-review-graph) (MIT, v2.3.1, 1022 forks)
**Purpose**: AI-powered code analysis via Tree-sitter AST parsing + SQLite knowledge graph. 22 MCP tools, 30+ language support, D3.js visualization. Claims 8.2x avg token reduction for AI-assisted code review.

**Key question**: What does ADA gain vs what it already has?

---

## ADA Already Has a Superior Code Graph

ADA's `codebase-memory` MCP is **more sophisticated** than code-review-graph in most dimensions:

| Dimension | codebase-memory (ADA) | code-review-graph |
|-----------|----------------------|-------------------|
| **Nodes** | 63,446 (12 types) | Fewer (5 types: File, Class, Function, Type, Test) |
| **Edges** | 223,346 (19 types) | Fewer (7 types) |
| **Communities** | 6,669 detected | Leiden algo (optional igraph dep) |
| **Routes** | 7,694 mapped | No route concept |
| **HTTP_CALLS** | 2,390 cross-service | Not supported |
| **ASYNC_CALLS** | 153 mapped | Not supported |
| **USAGE/WRITES** | 76,397 read/write refs | Not supported |
| **Git coupling** | FILE_CHANGES_WITH | Not supported |
| **OTel traces** | Ingestion supported | Not supported |
| **Query language** | Cypher-like | Predefined queries only |
| **ADR** | Built-in management | Not supported |
| **Incremental** | Yes (hash-based) | Yes (<2s) |
| **Search** | Graph + text search | Hybrid FTS5 + embeddings + RRF |

**Verdict**: Adopting code-review-graph wholesale would be a **downgrade**. Cherry-pick the gaps instead.

---

## Recommended Adoptions (Ranked by Value)

### 1. D3.js Interactive Code Visualization (HIGH VALUE)

**Gap**: ADA has zero visual representation of its 63K-node code graph. This is the biggest miss.

**What to take**: The `visualization.py` module and its embedded D3.js template
- Force-directed graph with physics simulation
- Community-colored nodes (ADA already has 6,669 communities)
- Zoom/drag, real-time search highlighting
- Drill-down community expansion
- Node metadata tooltips
- 4 rendering modes (full, community, file, auto)

**Implementation approach**:
- New frontend page: `/code-architecture`
- Backend endpoint feeds graph data from codebase-memory MCP (not SQLite - use existing graph)
- D3.js renders in a React wrapper component
- Filter by: community, file path, node type, edge type
- Click-through to source files

**Effort**: Medium (2-3 days). The D3.js template is self-contained HTML/JS. Need React wrapper + API endpoint to query codebase-memory and return JSON subgraphs.

---

### 2. Execution Flow Detection + Criticality Scoring (HIGH VALUE)

**Gap**: codebase-memory has `entry_points` but no full flow path tracing with multi-factor criticality scoring.

**What to take**: The `flows.py` module's approach:
- **Entry point detection**: True roots (no inbound calls), framework decorators (`@app.get`, `@celery.task`), conventional names (`main`, `test_*`, `handle_*`)
- **Criticality scoring** (5 weighted factors):
  - File spread (30%) - how many files does the flow touch?
  - External calls (20%) - how many external services?
  - Security sensitivity (25%) - auth, payment, admin patterns?
  - Test coverage gap (15%) - untested paths?
  - Depth (10%) - how deep is the call chain?

**Where it plugs in**:
- Feed into `enhancement_manager.py` to prioritize fixes on critical flows
- Feed into COS `regression_watcher.py` to focus monitoring on high-criticality paths
- Show in the D3.js visualization (color edges by criticality)

**Effort**: Medium (1-2 days). Build as a new service that queries codebase-memory's `trace_call_path` and computes criticality scores.

---

### 3. Multi-Factor Blast Radius Risk Scoring (HIGH VALUE)

**Gap**: codebase-memory's `detect_changes` uses simple hop-depth risk (hop1=CRITICAL, hop2=HIGH, etc.). code-review-graph uses 5-factor scoring.

**What to take**: The `changes.py` risk scoring model:
1. **Flow participation**: +0.05 per critical flow the node is in (cap 0.25)
2. **Cross-community callers**: +0.05 per community boundary crossing (cap 0.15)
3. **Test coverage**: +0.30 if untested, +0.05 if tested
4. **Security keywords**: +0.20 if name matches auth/payment/admin patterns
5. **Caller count**: callers/20 (cap 0.10)

**Where it plugs in**:
- Enhance the existing `detect_changes` output with richer risk scores
- Feed into code review agent to prioritize review focus
- Show in PR review workflow (which files are highest risk?)

**Effort**: Low (0.5-1 day). Pure computation on top of existing graph data. codebase-memory already has communities, caller counts, and test edges.

---

### 4. Dead Code Detection (HIGH VALUE)

**Gap**: ADA's QA agent scans for anti-patterns but not dead code (unused functions/classes).

**What to take**: The concept from `refactor.py` - functions with 0 inbound CALLS edges, excluding entry points.

**The data already exists** in codebase-memory:
```
search_graph(relationship='CALLS', direction='inbound', max_degree=0, exclude_entry_points=true)
```

**Where it plugs in**:
- Add as a new scan type in `intelligent_qa_agent.py`
- Report dead functions/classes in QA reports
- Could auto-create cleanup tasks in sprint system

**Effort**: Low (0.5 day). Just wire the existing codebase-memory query into QA scanning.

---

### 5. Hybrid Search with RRF Ranking (MEDIUM VALUE)

**Gap**: codebase-memory has separate text search (`search_code`) and graph search (`search_graph`). code-review-graph merges them with Reciprocal Rank Fusion.

**What to take**: The search merging strategy from `search.py`:
- Run both FTS5 (keyword) and vector (semantic) searches
- Merge via RRF with smart boosting (PascalCase → Classes, snake_case → Functions)
- Fallback chain: hybrid → FTS5 → LIKE

**Where it plugs in**: ADA Brain / AskADA could use this for better code-aware answers.

**Effort**: Medium (1-2 days). Need to implement RRF merging layer.

---

### 6. Auto-Wiki / Architecture Documentation (MEDIUM VALUE)

**Gap**: ADA has manually maintained topic files. code-review-graph auto-generates wiki from community structure.

**What to take**: The `wiki.py` concept - generate per-community markdown docs with:
- Community members, entry points, flows
- Cross-community dependency mapping
- Root index with sortable table

**Consideration**: ADA's manually maintained topic files are higher quality than auto-generated wikis. This would be a **supplement**, not replacement. Could auto-generate a "Code Structure" wiki that complements the hand-written topic files.

**Effort**: Medium (1-2 days). Query codebase-memory communities + trace_call_path, generate markdown.

---

### 7. Refactoring Preview (LOW VALUE)

**What it offers**: Rename preview (show all affected locations before renaming), dead code suggestions.

**Why low**: Claude Code + codebase-memory already provides rename-aware editing. The dead code piece is covered by item #4 above.

**Skip**.

---

### 8. Multi-Repo Cross-Search (LOW VALUE)

**What it offers**: Search across multiple registered repositories.

**Why low**: ADA is a single-repo application. No need.

**Skip**.

---

## Summary: What to Take

| # | Feature | Value | Effort | Priority |
|---|---------|-------|--------|----------|
| 1 | D3.js Code Architecture Visualization | HIGH | 2-3 days | P1 |
| 2 | Execution Flow + Criticality Scoring | HIGH | 1-2 days | P1 |
| 3 | Multi-Factor Blast Radius Scoring | HIGH | 0.5-1 day | P1 |
| 4 | Dead Code Detection in QA | HIGH | 0.5 day | P1 |
| 5 | Hybrid Search with RRF | MEDIUM | 1-2 days | P2 |
| 6 | Auto-Wiki Generation | MEDIUM | 1-2 days | P2 |
| 7 | Refactoring Preview | LOW | - | Skip |
| 8 | Multi-Repo Search | LOW | - | Skip |

**Total for P1 items**: ~4-6.5 days of work
**Total for P2 items**: ~2-4 days of work

## Key Insight

**Don't install code-review-graph as a dependency.** ADA's codebase-memory graph is already richer (19 edge types vs 7, 63K nodes, HTTP/async cross-service tracking, OTel traces). Instead, **port the 4-6 specific algorithms/UI patterns** listed above into ADA's existing architecture. This avoids:
- Duplicate graph storage (SQLite + codebase-memory)
- Conflicting MCP tool namespaces (22 new tools competing with existing ones)
- Maintenance burden of an external dep that may diverge
- Losing ADA's superior edge types (HTTP_CALLS, ASYNC_CALLS, USAGE, WRITES)

---

## Implementation Plan (if approved)

### Phase 1: Quick Wins (1-2 days)
1. **Dead code detection** - Wire `search_graph(max_degree=0, exclude_entry_points=true)` into QA agent
2. **Multi-factor risk scoring** - Add scoring layer on top of `detect_changes` output

### Phase 2: Execution Flows (1-2 days)
3. **Flow detection service** - New `backend/services/execution_flow_service.py`
4. **Criticality scoring** - 5-factor model from code-review-graph
5. **Wire into enhancement_manager** and COS

### Phase 3: Visualization (2-3 days)
6. **Backend**: New router `backend/routers/code_architecture.py` - endpoints to serve subgraph JSON from codebase-memory
7. **Frontend**: New page `/code-architecture` with D3.js force-directed graph
8. **Features**: Community coloring, search, drill-down, criticality overlay

### Phase 4: Search Enhancement (1-2 days)
9. **RRF merging layer** for ADA Brain code-aware search
10. **Auto-wiki generation** for architecture docs

## Verification
- Dead code: Run QA scan, verify it finds known unused functions
- Risk scoring: Run detect_changes on a recent PR, compare old vs new risk output
- Visualization: Navigate to `/code-architecture`, verify graph renders with community colors
- Flows: Query execution flows, verify entry points match known routers
