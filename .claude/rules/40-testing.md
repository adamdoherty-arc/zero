# 40 — Testing + troubleshooting (always loaded)

## Smoke testing after changes

After ANY rebuild, verify before declaring the task done:

```bash
# 1. Containers healthy?
docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero

# 2. API responds?
curl http://localhost:18792/api/health

# 3. Frontend reachable?
curl -I http://localhost:5173

# 4. LLM gateway alive?
curl http://localhost:4444/health/liveliness
curl http://localhost:18800/v1/models
```

If any of these fail, fix-on-sight — don't declare done.

## CI: golden-set carousel V2

The carousel/content pipeline has a CI golden-set test (V2) that validates output against curated expected results. Run before merging changes to the content pipeline:

```bash
cd backend && pytest tests/test_carousel_golden_v2.py -v
```

The golden set lives at `backend/tests/fixtures/carousel_golden_v2/`. If you intentionally change carousel output, regenerate goldens with the documented refresh script and review the diff before committing.

## Voice UX verification

Reachy voice surface needs explicit verification because failures are silent:

1. Open `/reachy` in the UI. Confirm `StreamingHealthCard` shows green for Robot / Daemon API / Video / Audio.
2. If host_agent is unreachable, `HostAgentOfflineBanner` (amber) shows at the top. Restart via Reachy DaemonPanel "Start daemon" — don't reach for scheduled tasks.
3. Trigger `InteractiveModeBar` (TopBar). Verify Local realtime path connects (Whisper → vLLM qwen3-chat → Piper/edge-tts).
4. Check `LLMStatusBadge` — green dot means the active brain probe (1-token, 15s cache) is healthy.

## Proactive monitoring

When starting a session or checking the system:
1. `docker ps --format "table {{.Names}}\t{{.Status}}"`
2. `docker logs --tail 100 zero-gateway 2>&1 | grep -i "error\|fail\|warn"`
3. Report and fix any issues before proceeding.

## Common Issues (fix-on-sight)

- **No response from chat**: Check `auth-profiles.json` exists and shared-litellm + vllm-chat are healthy:
  ```bash
  curl http://localhost:4444/health/liveliness
  curl http://localhost:18800/v1/models
  ```
- **WhatsApp disconnected**:
  ```bash
  docker exec -it zero-gateway node dist/index.js configure --section channels
  ```
- **API 500 errors**: `docker logs zero-api` — read the traceback, fix the cause.
- **Frontend not loading**: Verify zero-api is running on port 18792 and `zero-ui` is healthy.

## SEARCH BEFORE EXPLORING

Before using Glob/Grep to explore the codebase, use QMD MCP tools for documentation lookup:

- `qmd_search "keyword query"` — fast BM25 keyword search across all project .md docs
- `qmd_vsearch "conceptual query"` — semantic search by meaning
- `qmd_query "complex question"` — hybrid BM25 + vector + LLM re-ranking
- `qmd_get "path/to/file.md"` — retrieve full document content
- `qmd_multi_get "docs/product/*.md"` — retrieve multiple docs by pattern

**When to use which:**
- **QMD**: discovering relevant guides, "how does X work" questions across docs.
- **Direct Read**: when you know the exact file path.
- **Glob/Grep**: searching `.py`/`.tsx` source code (QMD only indexes `.md`).
