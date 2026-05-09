# /zero-brain

Zero's brain is a closed-loop learning engine that continuously learns, self-benchmarks, evolves prompts, and improves without being asked. It coordinates 6 subsystems: episodic memory, outcome learning, prompt evolution, content learning, employee benchmarking, and reflection.

## API Base

All endpoints at `http://localhost:18792/api/brain/` with Bearer token auth.

## Modes

### `--status` — Brain Dashboard
```bash
curl -s http://localhost:18792/api/brain/status -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | python -m json.tool
```
Shows: overall score (0-100), 10-dimension breakdown, weakest dimension, total memories, total outcomes, active experiments, last benchmark/learning cycle times.

### `--benchmark` — Run Full Benchmark
```bash
curl -s -X POST http://localhost:18792/api/brain/benchmark -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" | python -m json.tool
```
Runs the 12-dimension employee benchmark (Content Brain v2):
- Content Quality (15%) — engagement, scripts generated, content published
- Research Depth (12%) — completed reports + LLM quality grading
- Task Execution (12%) — agent task completion ratio
- Learning Velocity (10%) — score improvement rate over last 5 snapshots
- System Health (10%) — scheduler job success rate 24h
- Experiment Rigor (10%) — experiment + council completion rate
- Cost Efficiency (8%) — LLM cost/output ratio
- Communication Quality (8%) — LLM grades last 5 briefings
- Trending Alignment (8%) — % of content tied to active release signal
- Swarm Consensus Quality (7%) — avg swarm prediction confidence
- Calibration Accuracy (5%) — MAE from outcome predictions
- Calibration Per Agent (5%) — per-role inverse MAE

### `--improve [dimension]` — Auto-Improve
```bash
curl -s -X POST "http://localhost:18792/api/brain/improve?dimension=content_quality" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--learn` — Learning Insights
```bash
curl -s "http://localhost:18792/api/brain/learnings?days=7&limit=20" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s "http://localhost:18792/api/brain/calibration" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s "http://localhost:18792/api/brain/outcomes?domain=content&limit=20" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--memory <query>` — Search Episodic Memory
```bash
curl -s "http://localhost:18792/api/brain/memory?q=tiktok+engagement&limit=10" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--prompts` — Prompt Evolution
```bash
curl -s "http://localhost:18792/api/brain/prompts?task_type=content_generation" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s "http://localhost:18792/api/brain/prompts/best?task_type=content_generation" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--cycles` — Learning Cycles
```bash
curl -s "http://localhost:18792/api/brain/cycles?limit=10" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s -X POST http://localhost:18792/api/brain/cycles/run -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--content` — Content Intelligence
```bash
curl -s http://localhost:18792/api/brain/content/insights -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s http://localhost:18792/api/brain/content/strategies -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s http://localhost:18792/api/brain/content/posting-times -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--trending` — Trend Intelligence (Content Brain v2)
```bash
curl -s "http://localhost:18792/api/trends/signals?days=7" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s "http://localhost:18792/api/trends/upcoming-releases?days_ahead=14" -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s -X POST http://localhost:18792/api/trends/refresh -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s -X POST http://localhost:18792/api/trends/link-unprocessed -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--swarm` — Multi-agent swarm (opt-in per carousel)
```bash
# Request a carousel evaluated + critiqued by 7-role swarm
curl -sX POST http://localhost:18792/api/characters/{id}/carousels \
  -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN" \
  -d '{"angle":"hidden_truths","use_swarm":true}'
curl -s http://localhost:18792/api/brain/employee/agent-stats -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

### `--breed` — Prompt Breeder
```bash
curl -sX POST "http://localhost:18792/api/brain/prompts/breed?task_type=carousel_generation" \
  -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
# omit task_type to breed all
```

### `--employee` — Dashboard
Browse `http://localhost:5173/brain/employee` for the live dashboard. Backend:
```bash
curl -s http://localhost:18792/api/brain/employee/overview -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s http://localhost:18792/api/brain/employee/agent-stats -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s http://localhost:18792/api/brain/employee/trending -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
curl -s http://localhost:18792/api/brain/employee/cost -H "Authorization: Bearer $ZERO_GATEWAY_TOKEN"
```

## Architecture

Core subsystems: episodic_memory_service, outcome_learning_service, prompt_evolution_service, content_learning_engine, employee_benchmark_service, reflection_service, zero_brain_service.

Content Brain v2 adds: trend_intelligence_service, content_swarm_service (7 roles + weighted consensus), prompt_breeder_service, competitor_content_service.

Integration: content_agent_service (outcomes), tiktok_video_service (prompt enrichment), tiktok_shop_service (approvals), deep_research_service (findings), council_service (decisions), continuous_enhancement_service (enhancements), character_content_service (swarm opt-in via use_swarm=true or settings.character_swarm_enabled), character_discovery_service (from_trend_signal for release-aware priority promotion).

DB tables:
- Migration 018: episodic_memories, brain_outcome_records, prompt_variants, benchmark_scores, benchmark_history, learning_cycles, content_experiments.
- Migration 031: trending_signals (source, release_date, signal_strength, linked_character_ids, linked_media_title_ids).
- Migration 032: agent_predictions (role_name, phase=pre_gen|post_gen, predicted_engagement, confidence, vote, outcome_engagement, calibration_error).
- Migration 033: competitor_content_samples (niche, platform, hook_text, engagement_rate, 30-day decay).
