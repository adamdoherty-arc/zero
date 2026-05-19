# Prediction-Market Removal — 2026-05-18 (Sprint S2.5)

Zero's prediction-market subsystem was removed because **ADA's Unusual Whales
pipeline is the canonical source** for whale, options-flow, and
prediction-market data. Maintaining two ingestion paths drifted; deduplicating
to ADA is the correct architecture under the Legion-as-management-plane plan.

## Original files (archived here)

- `prediction_market_service.py` — Kalshi + Polymarket sync, bettor tracking, ADA push
- `prediction_legion_manager.py` — local sprint-status reporter (despite name, unrelated to Legion project)
- `prediction_markets_router.py` — `/api/prediction-markets/*` REST API
- `prediction_market_models.py` — Pydantic request/response models
- `test_prediction_market_parsing.py` — pytest cases

## What changed in the live tree

- `app/main.py` — removed router import + `app.include_router(prediction_markets.router, ...)` call
- `app/services/scheduler_service.py` — removed 6 cron entries (`prediction_market_sync`, `prediction_price_snapshot`, `prediction_bettor_discovery`, `prediction_research`, `prediction_push_to_ada`, `prediction_quality_check`) and their dispatch dict entries
- `app/services/orchestration_graph.py` — `prediction_market_node()` replaced with a redirect stub
- `app/services/prediction_market_service.py` — replaced with a stub that `raise ImportError` so any missed reference surfaces during boot
- `app/services/prediction_legion_manager.py` — same stub pattern
- `app/routers/prediction_markets.py` — empty router (preserved so accidental imports don't crash)

## Remaining manual steps

1. **Drop tables** (after `pg_dump` backup):
   ```sql
   -- Backup first:
   pg_dump -h localhost -p 5434 -U zero -d zero \
     -t prediction_markets -t prediction_bettors -t prediction_snapshots \
     -f C:\code\Zero\.archive\2026-05-18-prediction-market-removal\zero-prediction-tables.sql

   -- Then drop:
   DROP TABLE IF EXISTS prediction_snapshots CASCADE;
   DROP TABLE IF EXISTS prediction_bettors CASCADE;
   DROP TABLE IF EXISTS prediction_markets CASCADE;
   ```
2. **Remove the SQLAlchemy model classes** from `app/db/models.py` (lines ~1036–1095:
   `PredictionMarketModel`, `PredictionBettorModel`, `PredictionSnapshotModel`).
   Done after the tables are dropped so model removal doesn't precede the DDL change.
3. **Remove the routing keyword** `"prediction_market"` from the orchestrator router
   in `app/services/orchestration_graph.py` (the node is now a stub but the routing
   list still mentions it). Optional — the stub returns a friendly redirect.
4. **Delete `app/routers/prediction_markets.py`** and `app/services/prediction_market_service.py` once
   step 2 is complete and tests are green.
5. **UI**: remove the prediction-market tab from `frontend/src/pages/OrchestratorPage.tsx`.

## Rollback

`Copy-Item C:\code\Zero\.archive\2026-05-18-prediction-market-removal\*.py
C:\code\Zero\backend\app\<original-paths>\` and revert the live-tree edits.
The git history of `app/main.py`, `scheduler_service.py`, and
`orchestration_graph.py` shows the exact diff to revert.
