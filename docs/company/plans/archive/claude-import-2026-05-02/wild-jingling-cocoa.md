# Learn-13: External Knowledge Acquisition

## Context

Legion has a complete learning infrastructure (KnowledgeSourceDB, 8 specialist agents, episodic memory, learning engine, cross-project aggregator) but **no actual external data fetching**. The `BaseLearningAgent.learn()` method just logs "Learning source available" and returns. The `KnowledgeIngestionService.ingest_knowledge()` requires content to be passed in — there is no fetcher.

**Goal**: Make Legion discover repos *similar* to each managed project on GitHub, learn architecture/code/dependency patterns from them, and apply that knowledge to improve the user's projects over time. Also ingest curated RSS feeds for framework updates and security advisories.

This closes the loop: external knowledge → `KnowledgeSourceDB` → automatic agent prompt enrichment via `format_domain_context()` → improvement work items via work discovery.

---

## Architecture

```
ExternalKnowledgeDaemon (every 6h, supervised, gated by ENABLE_EXTERNAL_KNOWLEDGE)
  │
  ├── Phase 1: Discover Similar Repos
  │     For each managed project's tech stack:
  │       GitHub Search API: GET /search/repositories?q=topic:fastapi+language:python&sort=stars
  │     Upsert top results into GitHubRepoDB
  │     (~12 search queries, ~6 managed projects × 2 queries each)
  │
  ├── Phase 2: Deep Scan Best Repos
  │     Pick top 15 unscanned repos (by stars, recently pushed)
  │     Fetch README + dependency files (package.json, requirements.txt)
  │     LLM-summarize into architecture/pattern knowledge
  │     Store in KnowledgeSourceDB with managed_project applicability
  │     (~45 API calls, ~15 LLM calls)
  │
  ├── Phase 3: Feed/Article Ingestion
  │     Parse curated RSS feeds (FastAPI, React, SQLAlchemy, LangChain, Docker, Python security)
  │     LLM-summarize new articles → KnowledgeSourceDB
  │     (~20 HTTP fetches, ~10 LLM calls)
  │
  ├── Phase 4: Cross-Reference Analysis
  │     Compare scanned repo patterns against each managed project
  │     LLM identifies: newer deps, better patterns, missing practices
  │     Store as cross-reference entries (tag: "cross_reference")
  │     (~6 LLM calls, one per managed project)
  │
  └── Phase 5: Generate Work Items
        High-relevance cross-refs (score >= 0.7) → IdeaDB entries
        WorkDiscovery source #10 picks these up
        (DB writes only)
```

**Total per cycle**: ~57 GitHub API calls (budget: 5000/hr), ~31 LLM calls through Ollama semaphore (~10 min), ~20 feed fetches. Runs every 6 hours. All phases error-isolated.

---

## Files to Create (6 new files)

### 1. `backend/app/models/external_knowledge.py`
DB model + Pydantic schemas. Pattern: [ollama_manager.py](backend/app/models/ollama_manager.py)

**GitHubRepoDB** (table: `github_repos`):
- `id`, `github_id` (bigint, unique — GitHub's numeric repo ID)
- `full_name` ("owner/repo"), `owner`, `name`, `description`, `html_url`
- `default_branch`, `language` (primary), `languages` (JSON all), `topics` (JSON)
- `stargazers_count`, `github_updated_at`, `github_pushed_at`
- `is_fork`, `is_archived`, `size_kb`
- `discovered_via` (str) — which managed project's search found this ("legion", "ada", etc.)
- `managed_project_id` (nullable FK → projects) — set if this IS a managed repo
- `last_scanned_at`, `scan_status` ("pending"/"scanned"/"error"/"skipped")
- `scan_summary` (Text — LLM summary of the repo)
- `tech_stack_detected` (JSON), `patterns_extracted` (JSON), `dependencies_extracted` (JSON)
- `knowledge_entries_created` (int)
- `created_at`, `updated_at`
- Indexes: `(full_name)`, `(language)`, `(scan_status, last_scanned_at)`, `(discovered_via)`

**Pydantic schemas**: `GitHubRepoResponse`, `ExternalKnowledgeStatsResponse`, `CrossReferenceResponse`

### 2. `backend/app/services/github_repo_scanner.py`
GitHub API client for discovering and scanning repos.

- `GitHubRepoScanner` class
- `discover_similar_repos(project_name, tech_stack, topics)`:
  - `GET /search/repositories?q=topic:{topic}+language:{lang}&sort=stars&per_page=30`
  - Upsert results into GitHubRepoDB, mark `discovered_via=project_name`
  - Skip forks, archived, tiny repos (<10KB)
- `scan_repo(full_name)`:
  - `GET /repos/{owner}/{name}/readme` (Accept: application/vnd.github.raw) → README text
  - `GET /repos/{owner}/{name}/contents/package.json` or `requirements.txt` → deps
  - LLM-summarize README: extract architecture decisions, key patterns, notable practices
  - Parse dependencies into structured list
  - Return `{summary, tech_stack, patterns, dependencies}`
- `_github_request(method, path)` — httpx with token auth, 3x retry, 429 backoff, rate limit tracking
- `_parse_requirements_txt(content)` → `[{name, version_spec}]`
- `_parse_package_json(content)` → `[{name, version}]`
- `_build_search_queries(tech_stack)` → generate 2 search queries per project (by language+topic)

### 3. `backend/app/services/feed_ingestion_service.py`
RSS/Atom feed parser and article ingester.

- `FeedIngestionService` class
- `ingest_all_feeds()` — iterate EXTERNAL_KNOWLEDGE_FEEDS config, fetch + parse + ingest
- `_fetch_and_parse_feed(url)` — httpx GET, XML parse with `xml.etree.ElementTree` (no new deps)
- `_extract_entries(xml_root)` → `[{title, link, published, summary}]` — handles both RSS 2.0 and Atom
- `_fetch_article_text(url)` → strip HTML tags via regex, truncate to 3000 chars
- `_map_feed_to_domain(feed_key)` → `KnowledgeDomain`
- Dedup: check `KnowledgeSourceDB.source_url` before ingesting
- Rate limit: `asyncio.sleep(2)` between fetches
- Feeds content into `KnowledgeIngestionService.ingest_knowledge()` directly

### 4. `backend/app/services/external_knowledge_daemon.py`
Main daemon orchestrator. Pattern: [ollama_manager_service.py](backend/app/services/ollama_manager_service.py)

- `ExternalKnowledgeDaemon` class (singleton)
- `run_cycle()` — 5 phases, each wrapped in try/except
- Phase 1: iterate `MANAGED_PROJECTS`, call `scanner.discover_similar_repos()`
- Phase 2: query `GitHubRepoDB` for top 15 unscanned by stargazers, call `scanner.scan_repo()`, pipe results through `KnowledgeIngestionService.ingest_knowledge()`
- Phase 3: call `FeedIngestionService.ingest_all_feeds()`
- Phase 4: `_cross_reference()` — for each managed project, query recent knowledge entries from similar repos, LLM-analyze for applicable improvements
- Phase 5: `_generate_ideas()` — cross-ref entries with `relevance_score >= 0.7` and `times_used == 0` → create `IdeaDB` entries
- **LLM backpressure**: before each LLM call, check `UnifiedLLMService._ollama_queue_depth`; if > 5, sleep(10)
- **Prometheus metrics** (module-level):
  - `legion_ext_knowledge_repos_discovered` (Counter)
  - `legion_ext_knowledge_repos_scanned` (Counter)
  - `legion_ext_knowledge_articles_ingested` (Counter)
  - `legion_ext_knowledge_cross_refs_created` (Counter)
  - `legion_ext_knowledge_cycle_duration_seconds` (Histogram)
- `start_external_knowledge_daemon()` — 120s startup delay, then loop every 6h
- Skip entire cycle if `GITHUB_TOKEN` not set (phases 1-2 need it, 3-5 still run with cached data)

### 5. `backend/app/api/endpoints/external_knowledge.py`
API endpoints for visibility and manual control.

- `GET /external-knowledge/repos` — list discovered repos (paginated, filter by language/scan_status/discovered_via)
- `GET /external-knowledge/repos/{repo_id}` — detail with patterns + linked knowledge entries
- `GET /external-knowledge/stats` — repos discovered/scanned, knowledge entries, feed articles, last cycle time
- `GET /external-knowledge/feeds` — configured feeds with article counts
- `POST /external-knowledge/trigger-scan` — manually trigger daemon cycle (returns immediately)
- `GET /external-knowledge/cross-references/{project_id}` — improvement suggestions for managed project

### 6. `backend/alembic/versions/024_add_github_repos_table.py`
Migration creating `github_repos` table with all columns and indexes.

---

## Files to Modify (6 existing files)

### 1. [backend/app/models/__init__.py](backend/app/models/__init__.py)
Add imports: `GitHubRepoDB`, `GitHubRepoResponse`, `ExternalKnowledgeStatsResponse`

### 2. [backend/app/core/legion_config.py](backend/app/core/legion_config.py)
Add config block:
```python
EXTERNAL_KNOWLEDGE_FEEDS = {
    "fastapi-releases": {"url": "https://github.com/tiangolo/fastapi/releases.atom", "domain": "backend"},
    "react-blog": {"url": "https://react.dev/blog/rss.xml", "domain": "ui"},
    "sqlalchemy-releases": {"url": "https://github.com/sqlalchemy/sqlalchemy/releases.atom", "domain": "database"},
    "langchain-releases": {"url": "https://github.com/langchain-ai/langchain/releases.atom", "domain": "ai"},
    "docker-blog": {"url": "https://www.docker.com/blog/feed/", "domain": "devops"},
    "python-security": {"url": "https://github.com/pyupio/safety-db/commits/master.atom", "domain": "security"},
}
EXTERNAL_KNOWLEDGE_SCAN_INTERVAL_HOURS = 6
EXTERNAL_KNOWLEDGE_MAX_REPOS_PER_CYCLE = 15
```

### 3. [backend/main.py](backend/main.py) (~line 471, after ollama_manager block)
Add supervised daemon registration block (same pattern as ollama_manager at line 462-469).

### 4. [backend/app/api/router_registry.py](backend/app/api/router_registry.py)
Import `external_knowledge` endpoint module, register router under Learning & Analytics section.

### 5. [backend/app/services/work_discovery_service.py](backend/app/services/work_discovery_service.py)
Add source #10: `_discover_from_external_knowledge()` — query `KnowledgeSourceDB` where `tags` contains `"cross_reference"`, `active=True`, `times_used == 0`. Convert to work items following existing source pattern.

### 6. [backend/app/agents/learning/base_learning_agent.py](backend/app/agents/learning/base_learning_agent.py) (line 66-91)
No functional change needed — `learn()` already logs source availability. The daemon handles actual fetching. The agents automatically consume ingested knowledge via `_enrich_with_knowledge()` → `format_domain_context()`. (Optional: update log message to reference external knowledge daemon.)

---

## Sprint Tasks (7 tasks)

| # | Task | SP | Files |
|---|------|----|-------|
| 1 | DB model + migration | 2 | `models/external_knowledge.py`, `models/__init__.py`, `alembic/versions/024_*` |
| 2 | GitHub Repo Scanner | 3 | `services/github_repo_scanner.py` |
| 3 | Feed Ingestion Service | 3 | `services/feed_ingestion_service.py`, `core/legion_config.py` (feed config) |
| 4 | External Knowledge Daemon | 3 | `services/external_knowledge_daemon.py`, `main.py`, `core/legion_config.py` |
| 5 | Cross-Reference Engine + Work Discovery | 3 | Phase 4-5 in daemon, `services/work_discovery_service.py` source #10 |
| 6 | API Endpoints + Router | 2 | `api/endpoints/external_knowledge.py`, `api/router_registry.py` |
| 7 | Tests | 3 | `tests/services/test_external_knowledge.py` (~60 tests) |

---

## Key Design Decisions

1. **Search-based discovery, not user-repo listing**: Instead of `GET /user/repos`, we use `GET /search/repositories` with each managed project's tech stack as query terms. This finds the *best* repos in the ecosystem, not just the user's own repos.

2. **No new Python dependencies**: RSS parsing via `xml.etree.ElementTree` (stdlib). HTML stripping via regex. No `feedparser` or `beautifulsoup` needed.

3. **KnowledgeSourceDB is the sink**: All external knowledge flows through the existing `KnowledgeIngestionService.ingest_knowledge()` method. Zero changes needed for agents to consume it — they already call `format_domain_context()`.

4. **IdeaDB as the bridge to execution**: Cross-reference findings become IdeaDB entries (source=SYSTEM). WorkDiscovery already reads IdeaDB as source #1. This means external knowledge can produce sprints without any new execution wiring.

5. **LLM backpressure**: Daemon checks Ollama queue depth before each LLM call. Active sprints always take priority — the daemon yields when the system is busy.

---

## Verification Plan

1. **Migration**: `alembic upgrade head` succeeds, `github_repos` table exists
2. **Repo discovery**: `POST /external-knowledge/trigger-scan` → check `GET /external-knowledge/repos` shows repos similar to managed projects
3. **Repo scanning**: Top repos get README summaries in KnowledgeSourceDB (`GET /external-knowledge/stats` shows nonzero knowledge entries)
4. **Feed ingestion**: RSS feeds parsed, new articles in KnowledgeSourceDB with correct domains
5. **Cross-references**: `GET /external-knowledge/cross-references/3` returns suggestions for Legion
6. **Work discovery**: IdeaDB entries created from high-relevance findings
7. **Agent enrichment**: Call `GET /api/knowledge/coverage` — domains should show populated entries
8. **Docker**: `docker-compose build legion-backend && docker-compose up -d` succeeds with `ENABLE_EXTERNAL_KNOWLEDGE=true`
9. **Tests**: `python -m pytest tests/services/test_external_knowledge.py -v` all pass
