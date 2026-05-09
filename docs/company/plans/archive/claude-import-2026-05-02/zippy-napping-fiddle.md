# Plan: Create `contentai-platform-auditor` Skill

## Context

AIContentTools is a full-stack AI content generation platform with 18 Docker services, 103 backend Python files, 310+ frontend TypeScript files. There is no systematic way to evaluate whether the platform is healthy, modern, and well-integrated. The user needs a self-learning auditor skill (modeled after `legion-platform-auditor` and `ada advisor-audit`) that:

1. Reviews and grades every Docker service on necessity, health, and modernness
2. Grades every frontend page and backend feature group across 6 dimensions
3. Live-checks dependencies against PyPI/npm for currency and vulnerabilities
4. Self-learns across runs (delta tracking, adaptive weights, improvement patterns)
5. Auto-fixes small/medium issues after reporting (legion pattern)

---

## Files to Create (11 total)

| # | File | Purpose |
|---|------|---------|
| 1 | `.claude/skills/contentai-platform-auditor/SKILL.md` | Main skill definition (~600 lines) |
| 2 | `knowledge/audit_history.json` | Per-run snapshots with scores and deltas |
| 3 | `knowledge/dimension_weights.json` | 6 adaptive weights with evolution log |
| 4 | `knowledge/feature_catalog.json` | All features mapped to routes, APIs, files, importance |
| 5 | `knowledge/service_registry.json` | 18 Docker services with necessity grades |
| 6 | `knowledge/code_quality_baseline.json` | Anti-pattern counts for trend detection |
| 7 | `knowledge/dependency_health.json` | Package versions + freshness tracking |
| 8 | `knowledge/dead_features.json` | Features flagged as dead/non-functional |
| 9 | `knowledge/duplication_registry.json` | Known duplicate/overlapping capabilities |
| 10 | `knowledge/improvement_patterns.md` | Meta-learnings from cross-run analysis |
| 11 | `knowledge/improvement_log.md` | Per-run remediation notes |

All knowledge files go under `.claude/skills/contentai-platform-auditor/knowledge/`.

---

## SKILL.md Content Design

### Header (YAML Frontmatter)

```yaml
name: "contentai-platform-auditor"
description: "Comprehensive audit of all ContentAI services, features, dependencies, and code quality. Grades 18 Docker services + 28 features across 6 dimensions. Live-checks dependency versions. Self-learns across runs. Auto-fixes S/M issues."
version: "1.0.0"
metadata:
  contentai:
    category: "quality"
    triggers:
      - "platform audit"
      - "audit platform"
      - "full audit"
      - "service audit"
      - "platform grade"
      - "review platform"
      - "audit services"
      - "grade platform"
    requires:
      services: ["backend", "frontend", "postgres"]
```

### Execution Steps

#### Step 0: Load Previous State
Read all 10 knowledge files. If `audit_history.json` has empty `runs`, this is the first run — establish baseline with default weights.

#### Step 0.5: Backend Pre-check
```bash
curl -s --max-time 5 http://localhost:8085/health
```
If cold, warm caches by hitting `/api/gallery/generated/stats`, `/api/gallery/personas`, `/api/batch/queues`. Wait 5s.

#### Step 1: Docker Service Audit (18 services)

For each of the 18 Docker services, evaluate 5 sub-dimensions:

| Sub-Dimension | What to Check |
|---------------|---------------|
| **Necessity** (30%) | Is this service actively used? Does it have callers? Could it be removed or merged? |
| **Health** (25%) | Is the container running? Health check passing? Error rate in logs? |
| **Resource Cost** (15%) | GPU VRAM, RAM, CPU. Is the cost justified by usage? |
| **Modernness** (15%) | Is the image/version current? Any known CVEs? |
| **Configuration** (15%) | Health checks defined? Restart policy? Resource limits? Proper networking? |

**Service-by-service checks:**

```
PostgreSQL 16:   pg_isready + SELECT count(*) FROM information_schema.tables + index health
Redis 7:         redis-cli ping + INFO memory + INFO keyspace
Backend:         /health + router count + error rate from recent logs
Frontend:        HTTP 200 at :3001 + check nginx config + bundle size
ComfyUI:         /system_stats + GPU detection + loaded models
Open WebUI:      HTTP 200 at :3080 — QUESTION: redundant with frontend chat?
Celery Worker:   celery inspect ping + queue depth
Celery Beat:     ps check + schedule config
Qdrant:          HTTP :6337 + collection stats + embedding count
ChromaDB:        HTTP :8000 — QUESTION: redundant with Qdrant?
MinIO:           HTTP :9002 + bucket list + total object count
Prometheus:      HTTP :9091 + active targets count
Grafana:         HTTP :3003 + dashboard count
n8n:             HTTP :5678 + active workflow count
n8n Worker:      ps check — needed only if n8n uses queue mode
Whisper:         HTTP :9000 + any STT API calls in backend?
SadTalker:       HTTP :7862 + any talking-head endpoints called?
Stable Video:    HTTP :7864 + any video generation calls?
```

**Necessity grading:**
- **Essential** (90-100): Core loop depends on it, cannot function without
- **Recommended** (70-89): Adds significant value, removal would degrade experience
- **Optional** (40-69): Nice-to-have, could be disabled to save resources
- **Questionable** (0-39): Likely redundant or unused, candidate for removal

**Initial assessments (to validate at audit time):**
- Essential: postgres, redis, backend, frontend, comfyui, celery-worker, celery-beat
- Recommended: qdrant, n8n, prometheus
- Optional: grafana, minio, whisper, sadtalker, stable-video
- Questionable: chromadb (Qdrant does same job), open-webui (frontend has chat), n8n-worker (queue mode not confirmed)

#### Step 1.5: Feature Catalog Auto-Discovery
1. Read `frontend/src/main.tsx` — extract all route definitions (RouterProvider)
2. Read `backend/main.py` — extract all `app.include_router()` calls
3. Compare to `feature_catalog.json`
4. Flag NEW routes not in catalog, add with default importance 1.0
5. Flag REMOVED routes, mark as dead candidates

#### Step 2: Audit Each Feature (6 Dimensions)

**Audit scope: 16 frontend pages + 12 backend groups = 28 features**

**Frontend Pages (16):**

| Page | Route | Key Files | Importance |
|------|-------|-----------|------------|
| Gallery | `/examples` | `examples.tsx`, `gallery_api.py` | 1.5x |
| Batch/Jobs | `/jobs` | `jobs.tsx`, `batch_queue_manager.py` | 1.5x |
| Agent (Autonomous) | `/agent` | `agent.tsx`, `autonomous_agent_api.py` | 1.2x |
| Calendar | `/calendar` | `calendar.tsx`, `content_calendar_api.py` | 1.0x |
| Publishing | `/publishing` | `publishing.tsx`, `publishing_hub_api.py` | 1.0x |
| Strategy | `/strategy` | `strategy.tsx`, `content_strategy_api.py` | 1.0x |
| Video | `/video` | `video.tsx`, `video_generation_api.py` | 1.0x |
| Models | `/models` | `models.tsx`, `model_manager_api.py` | 1.0x |
| LoRA Training | `/lora` | `lora.tsx`, `lora_training_api.py` | 1.0x |
| Analytics | `/analytics` | `analytics.tsx`, `analytics_api.py` | 0.7x |
| Variations | `/variations` | `variations.tsx`, `content_variations_api.py` | 1.0x |
| Sprints | `/sprints` | `sprints.tsx`, `sprint_api.py` | 0.7x |
| Approval | `/approval` | `approval.tsx` | 0.7x |
| Autopilot | `/autopilot` | `autopilot.tsx` | 1.0x |
| Services | `/services` | `services.tsx` | 0.7x |
| UI Quality | `/ui-quality` | `ui-quality.tsx` | 0.7x |

**Backend Feature Groups (12):**

| Group | Key Files | Importance |
|-------|-----------|------------|
| Gallery System | `gallery_api.py`, `collections_api.py` | 1.5x |
| Persona System | `persona_detection.py`, `persona_repository.py`, `persona_import_api.py`, `persona_management_api.py`, `face_consistency_api.py`, `face_embeddings.py`, `enhanced_face_clustering_api.py` | 1.5x |
| Batch Generation | `batch_queue_manager.py`, `comfyui_batch_generator.py`, `flux2_multiref_workflow.py` | 1.5x |
| Autonomous AI | `autonomous_agent_api.py`, `crew_orchestrator.py`, `crews_api.py`, `content_agents.py` | 1.2x |
| Content Pipeline | `content_calendar_api.py`, `content_strategy_api.py`, `content_coach_api.py`, `content_intelligence.py`, `content_variations_api.py` | 1.0x |
| Publishing | `publishing_hub_api.py`, `social_publishing_api.py` | 1.0x |
| Video/Media | `video_generation_api.py`, `video_generation_service.py` | 1.0x |
| AI Services | `rag_system.py`, `llm_service.py`, `prompt_research_service.py`, `vision_review_service.py`, `self_learning_integration.py` | 1.2x |
| Analytics | `analytics_api.py`, `insights_api.py`, `feedback_loop_api.py`, `performance_api.py` | 0.7x |
| LoRA/Models | `lora_training_api.py`, `model_manager_api.py`, `models_config.py` | 1.0x |
| Chat | `chat/index.tsx`, `chat/[sessionId].tsx`, LLM streaming endpoints | 1.2x |
| Support Infra | `auth.py`, `cache.py`, `rate_limiter.py`, `websocket_manager.py`, `intelligent_logging.py` | 0.7x |

**6 Scoring Dimensions:**

| Dim | Name | Weight | What to Check |
|-----|------|--------|---------------|
| D1 | Functional Completeness | 25% | Page loads, APIs return data, no placeholders/TODOs |
| D2 | Data Quality | 20% | Real data (not dummy), freshness, completeness |
| D3 | Integration | 20% | Cross-feature links, data flow, WebSocket updates |
| D4 | UX/Performance | 15% | Loading states, error handling, responsive, <3s responses |
| D5 | Code Quality | 10% | Bare excepts, datetime safety, string enums, file size, prints |
| D6 | Dependency Modernness | 10% | Package currency vs PyPI/npm latest, no CVEs, no deprecated APIs |

**D6 Live Version Checks:**
```bash
# Python: check latest version on PyPI
pip index versions fastapi 2>/dev/null | head -1
# Or: curl -s https://pypi.org/pypi/fastapi/json | python -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"

# npm: check latest version
npm view react version 2>/dev/null
```

Check key packages: fastapi, react, vite, typescript, tailwindcss, langchain, crewai, torch, diffusers, pydantic, sqlalchemy, celery, redis, qdrant-client, chromadb, ollama.

**Scoring rubric per dimension:** Same as legion (90-100 A, 70-89 B/C, 50-69 D, 0-49 F).

#### Step 3: Calculate Grades

```
feature_score = D1*0.25 + D2*0.20 + D3*0.20 + D4*0.15 + D5*0.10 + D6*0.10
platform_score = weighted_average(all_feature_scores * importance_weights)
```

Use adaptive weights from `dimension_weights.json` (not hardcoded).

Grade mapping: 97-100 A+, 93-96 A, 90-92 A-, 87-89 B+, 83-86 B, 80-82 B-, 77-79 C+, 73-76 C, 70-72 C-, 60-69 D, 0-59 F.

#### Step 4: System Coherence Checks

**4a: Content Generation Pipeline Integrity**
```
Persona Detection (vision AI) → Face Embeddings (InsightFace)
  → Batch Queue (prompt research + ComfyUI) → Vision Review (quality scoring)
  → Gallery (storage + metadata) → Self-Learning (outcome recording)
  → Autonomous Agent (next batch planning)
```
Verify each stage's output is consumed by the next.

**4b: API Consistency**
Sample 10 endpoints across routers. Check response format, error format, naming.

**4c: UX Consistency**
Check 5+ pages for loading pattern, empty state, error display consistency.

**4d: Duplication Detection**
- Qdrant vs ChromaDB (both vector DBs)
- content_agents.py (LangGraph) vs crews_api.py (CrewAI) — both do content pipeline
- Open WebUI vs frontend chat — both chat interfaces
- analytics_api vs insights_api — both provide metrics

**4e: Dead Feature Detection**
Features with: zero inbound nav, all APIs erroring, no changes in 30+ days, score < 50.

**4f: Dependency Conflict Detection**
Known conflicts: crewai/tokenizers, numpy<2.0, langchain version range.

#### Step 5: Generate Report

```markdown
# ContentAI Platform Audit — {date}

## Platform Grade: {score}/100 ({grade}) [{delta from last}]

### Docker Service Grades (18 services)
| Service | Necessity | Health | Resource | Modern | Config | Overall | Recommendation |
|---------|-----------|--------|----------|--------|--------|---------|---------------|

### Feature Scores (ranked worst-first)
| Rank | Feature | Score | Grade | D1 | D2 | D3 | D4 | D5 | D6 | Trend |
|------|---------|-------|-------|----|----|----|----|----|----|-------|

### Top 10 Highest-Impact Improvements
| # | Feature | Current | Action | Impact | Effort |
|---|---------|---------|--------|--------|--------|

### Dependency Audit
| Package | Current | Latest | Behind | Risk |
|---------|---------|--------|--------|------|

### Services to Consider Removing/Disabling
| Service | Why | Savings | Alternative |

### Duplication Report
| Feature A | Feature B | Overlap | Recommendation |

### Dead Features
| Feature | Route | Last Modified | Issue | Recommendation |

### System Coherence
| Check | Status | Issues |

### Auto-Fixes Applied
| Issue | Category | Fix | Result |
```

#### Step 6: Update Knowledge Files
1. Append to `audit_history.json` (prune to 20 runs)
2. Update `feature_catalog.json` with discovered routes
3. Update `service_registry.json` with health/necessity grades
4. Update `dead_features.json`
5. Update `duplication_registry.json`
6. Update `dependency_health.json` with version check results
7. Update `code_quality_baseline.json` with anti-pattern counts
8. Update `improvement_patterns.md` with new learnings
9. Update `improvement_log.md` with this run's summary
10. Evolve `dimension_weights.json`: boost acted-on dims +0.5%, reduce ignored -0.25%, normalize to 1.0

#### Step 7: Self-Improvement Analysis
Compare to previous run: which features improved/regressed, which recommendations acted on/ignored, score trajectory, user priority pattern.

#### Step 8: Remediation (Auto-fix S/M items)

**8a: Triage by effort**
- S (<30 min, <3 files): Fix NOW
- M (30-90 min, 3-10 files): Fix NOW
- L (>90 min, >10 files): Log as recommendation, skip

**8b: Fix categories (in order)**
1. Container health (restart unhealthy services)
2. Code quality (bare excepts → proper logging, datetime safety)
3. Dependency updates (pip install --upgrade for safe updates)
4. Configuration gaps (health checks, restart policies)
5. Integration wiring (missing nav links, broken deep links)

**8c: Verify fixes** — Rebuild affected containers, curl endpoints, log results.

**8d: Safety rules**
- Never skip fixes to save time
- Test before committing
- One fix at a time
- Update baselines after each fix
- False positive verification before "fixing" anti-patterns
- Docker rebuild after code changes
- Max 10 min per fix category — defer complex items

### Modes

| Mode | Command | Scope | Time |
|------|---------|-------|------|
| Full | `/contentai-platform-auditor` | All services + features + deps | ~20 min |
| Quick | `--quick` | Only changed features since last run | ~8 min |
| Services | `--services` | Docker services only | ~5 min |
| Deps | `--deps` | Dependency audit only | ~5 min |
| Grade | `--grade` | Display current grades, no new audit | ~3 min |

---

## Knowledge File Initial Content

### audit_history.json
```json
{"runs": []}
```

### dimension_weights.json
```json
{
  "_schema_version": "1.0",
  "_description": "Adaptive dimension weights for ContentAI platform auditor. Weights evolve based on which improvements have the highest impact across runs.",
  "_last_updated": "2026-04-14",
  "_evolution_log": [
    {"date": "2026-04-14", "rationale": "Baseline weights. Equal emphasis on functional + data + integration as primary quality signals."}
  ],
  "functional_completeness": {"weight": 0.25, "initial": 0.25},
  "data_quality": {"weight": 0.20, "initial": 0.20},
  "integration": {"weight": 0.20, "initial": 0.20},
  "ux_performance": {"weight": 0.15, "initial": 0.15},
  "code_quality": {"weight": 0.10, "initial": 0.10},
  "dependency_modernness": {"weight": 0.10, "initial": 0.10}
}
```

### service_registry.json
Pre-populated with all 18 services, each with: name, container, image, ports, gpu, ram_estimate, purpose, necessity_assessment, initial_grade, notes.

### feature_catalog.json
Pre-populated with all 28 features (16 pages + 12 backend groups) mapped to: route, api_prefix, primary_files, hooks, importance, sub_tabs, deep_links.

### code_quality_baseline.json
```json
{
  "_schema_version": "1.0",
  "last_updated": "2026-04-14",
  "global": {
    "bare_except_count": null,
    "print_count": null,
    "string_enum_count": null,
    "unsafe_datetime_count": null,
    "silent_pass_count": null,
    "service_count": null,
    "page_count": null,
    "files_over_500_loc": []
  },
  "history": [],
  "next_targets": {
    "bare_except_count": 0,
    "print_count": 0,
    "silent_pass_count": 0
  }
}
```

### dependency_health.json
```json
{
  "_schema_version": "1.0",
  "last_checked": null,
  "python": {},
  "npm": {},
  "known_constraints": [
    {"package": "crewai", "constraint": "requires tokenizers~=0.20.3, conflicts with transformers>=4.47", "workaround": "Pin transformers<4.47"},
    {"package": "numpy", "constraint": "Pinned <2.0.0 due to ML library breaking changes", "workaround": "Keep <2.0 until ecosystem catches up"},
    {"package": "langchain", "constraint": "Pinned >=0.3.0,<1.3.0 — 1.3.0 doesn't exist yet", "workaround": "Safe range"}
  ],
  "history": []
}
```

### dead_features.json, duplication_registry.json
```json
{"features": [], "last_updated": "2026-04-14"}
```

### improvement_patterns.md
Empty template with headers for High-Impact Patterns, Meta-Patterns, and Dimension Weight Evolution.

### improvement_log.md
Empty template with header for chronological run notes.

---

## Verification Plan

1. **File structure**: `ls .claude/skills/contentai-platform-auditor/` shows SKILL.md + `knowledge/` with 10 files
2. **JSON validity**: `python -c "import json; json.load(open(f))"` for each .json file
3. **Skill loadable**: Invoke `/contentai-platform-auditor --grade` — should load knowledge files, report "first run, no previous data"
4. **Backend reachability**: `curl -s http://localhost:8085/health` returns 200
5. **Service checks work**: Docker container status commands return valid output
6. **Live dep check works**: `pip index versions fastapi` returns version info
7. **After first full run**: `audit_history.json` has 1 entry with scores, all knowledge files updated
