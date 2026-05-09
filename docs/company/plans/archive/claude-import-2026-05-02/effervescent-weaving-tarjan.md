# Plan: Fix Content Pipeline + Make It Run 24/7

## Context
The character carousel pipeline is dead despite 17 scheduler jobs running. Three root causes found through log analysis:

1. **MiniMax API 401 Unauthorized** - Circuit breaker is OPEN. All final reviews fail.
2. **Kimi K2.5 fallback returns empty content** - Kimi puts response in `reasoning_content` but the provider only checks that field when `thinking_mode=True`. Since fallbacks disable thinking_mode (unified_llm_client.py:556), the content comes back as `""`, causing `parse_json_response` to log `raw_length=0`.
3. **251 files uncommitted/undeployed** - New content variety system (5 templates, 7 hook styles, ranking carousels) only exists in working tree, not running container.
4. **Silent failures** - All scheduler jobs swallow exceptions. No alerts.

## Phase 1: Fix Kimi provider empty content bug
**File**: [backend/app/infrastructure/llm_providers/kimi_provider.py](backend/app/infrastructure/llm_providers/kimi_provider.py#L97-L105)

The fix: always check `reasoning_content` when `content` is empty, not only when `thinking_mode=True`. Kimi K2.5 can return reasoning_content even without explicit thinking mode.

```python
# Line 99-103: Change from:
if not content and thinking_mode:
    reasoning = data["choices"][0]["message"].get("reasoning_content", "")
    if reasoning:
        content = reasoning

# To:
if not content:
    reasoning = data["choices"][0]["message"].get("reasoning_content", "")
    if reasoning:
        content = reasoning
```

This is the PRIMARY fix. Once Kimi fallback actually returns content, final reviews will succeed even with MiniMax down.

## Phase 2: Update fallback chain - Kimi primary for final review, Ollama as last resort
**File**: `workspace/llm/router_config.json`

Change `character_content_review_final` routing:
- Primary: `kimi/kimi-k2.5` (Kimi is reliable and cheap)
- Fallback 1: `minimax/MiniMax-M2.7` (when/if MiniMax key is fixed)
- Fallback 2: `ollama/qwen3.6:35b-a3b-q8_0` (free local)

Same for `character_content_review_escalated`:
- Primary: `kimi/kimi-k2.5`
- Fallback 1: `minimax/MiniMax-M2.7`
- Fallback 2: `ollama/qwen3.6:35b-a3b-q8_0`

## Phase 3: Pass json_mode to final review LLM call
**File**: [backend/app/services/character_content_service.py](backend/app/services/character_content_service.py#L1863)

The `_final_review_carousel` calls `client.chat()` without `json_mode=True`. When falling back to Kimi/Ollama (which don't have native JSON enforcement like MiniMax), the LLM may return prose or markdown-wrapped JSON. Add `json_mode=True` to improve reliability:

```python
# Line 1863: Change from:
_fr_raw = await client.chat(
    prompt=prompt,
    system=_fr_system,
    task_type="character_content_review_final",
    temperature=0.3,
    max_tokens=2048,
)

# To:
_fr_raw = await client.chat(
    prompt=prompt,
    system=_fr_system,
    task_type="character_content_review_final",
    temperature=0.3,
    max_tokens=2048,
    json_mode=True,
)
```

## Phase 4: Add failure alerting to critical autopilot jobs
**File**: [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py#L2464)

Add UI notification on critical job failures so content pipeline issues are visible immediately. Use the existing `NotificationService.create_notification()` for these 4 critical jobs:
- `_run_character_content_generation` (line 2489)
- `_run_character_final_review_backfill` (line 2700)
- `_run_character_auto_approval` (line 2625)
- `_run_character_publish_backlog` (line 2638)

Pattern for each:
```python
except Exception as e:
    logger.error("job_name_failed", error=str(e))
    try:
        from app.services.notification_service import get_notification_service
        await get_notification_service().create_notification(
            title="Content Pipeline Alert",
            message=f"Job {job_name} failed: {str(e)[:200]}",
            source="scheduler",
            source_id=job_name,
        )
    except Exception:
        pass
```

Also change `_autopilot_disabled` to use `logger.warning` instead of `logger.info` (line 2608).

## Phase 5: Improve content generation job - generate more aggressively
**File**: [backend/app/services/scheduler_service.py](backend/app/services/scheduler_service.py#L2464-L2490)

Current `_run_character_content_generation` only generates for characters with `posts_created < 3` and caps at 3 per run (every 12 hours = max 6/day). This is too conservative for 24/7 content production.

Improvements:
- Raise per-run cap from 3 to 10
- Generate for all researched characters, not just those with < 3 posts
- Prioritize characters by `priority_tier` (priority > standard > probation)
- Use variety: rotate angles and templates across the batch
- Log which character + angle + template was generated for observability

## Phase 6: Commit and deploy all changes
- Commit all 251+ changed files (includes new content parameters, templates, variety system, and these fixes)
- Rebuild and restart zero-api:
  ```bash
  docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api
  ```
- Verify container healthy

## Verification
1. Watch logs for successful final reviews: `docker logs -f zero-api 2>&1 | grep "final_review_completed"`
2. Confirm no more `raw_length=0` errors
3. Confirm Kimi fallback returns actual content (look for `llm_fallback_attempt` followed by `final_review_completed`)
4. Check that new templates are being selected (storyline_recap, power_ranking, etc.)
5. Verify auto-approval fires: `grep "character_auto_approval_complete" `
6. Confirm notifications appear in UI on any job failure
7. Monitor for 15 min to ensure pipeline flows: draft -> ai_reviewed -> final_reviewed -> approved -> queued

## Critical Files
- `backend/app/infrastructure/llm_providers/kimi_provider.py` - Empty content bug fix
- `backend/app/services/character_content_service.py` - json_mode for final review
- `backend/app/services/scheduler_service.py` - Alerting + generation improvements
- `workspace/llm/router_config.json` - Fallback chain reorder
- `backend/app/infrastructure/unified_llm_client.py` - Fallback execution (read-only, for reference)
- `backend/app/infrastructure/circuit_breaker.py` - Circuit breaker (read-only, for reference)
