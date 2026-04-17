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
Runs the 10-dimension employee benchmark:
- Content Quality (15%) — engagement, scripts generated, content published
- Learning Velocity (15%) — score improvement rate over last 5 snapshots
- Research Depth (12%) — completed reports + LLM quality grading
- Task Execution (12%) — agent task completion ratio
- System Health (10%) — scheduler job success rate 24h
- Experiment Rigor (10%) — experiment + council completion rate
- Cost Efficiency (8%) — LLM cost/output ratio
- Communication Quality (8%) — LLM grades last 5 briefings
- Calibration Accuracy (5%) — MAE from outcome predictions
- Knowledge Growth (5%) — new memories vs prior 30 days

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

## Architecture

6 subsystems: episodic_memory_service, outcome_learning_service, prompt_evolution_service, content_learning_engine, employee_benchmark_service, reflection_service. Central hub: zero_brain_service. 9 scheduler jobs run 24/7. Frontend at /brain.

Integration: content_agent_service (outcomes), tiktok_video_service (prompt enrichment), tiktok_shop_service (approvals), deep_research_service (findings), council_service (decisions), continuous_enhancement_service (enhancements).

DB tables (migration 018): episodic_memories, brain_outcome_records, prompt_variants, benchmark_scores, benchmark_history, learning_cycles, content_experiments.
