# 60 — Database patterns (always loaded)

## Async everywhere

All DB I/O uses `async/await`. There is no sync DB path in Zero. If you see a sync `psycopg2` call, replace it with `asyncpg` and lift the caller to async.

## Pydantic validation

All request/response models validated through Pydantic. Don't pass dicts around — pass typed models. Validation errors at the boundary surface as 422s with structured fields, which is the contract the frontend expects.

## structlog logging

All logging routes through `structlog`. Don't use stdlib `logging` for new code. Structured fields make grep + dashboards possible:

```python
import structlog
logger = structlog.get_logger(__name__)

logger.info("sprint.created", sprint_id=sprint.id, project_id=7, source="zero")
```

## lru_cache singletons

Settings, clients, and other process-wide singletons use `@lru_cache()`:

```python
from functools import lru_cache

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

`get_settings()` (and similar) is the canonical accessor. Don't instantiate `Settings()` directly in handlers.

## asyncpg patterns

- Use a connection pool from the app lifespan, not per-request connections.
- Prepared statements for hot paths.
- Always parameterize — never f-string SQL.
- Long-running queries get explicit `timeout=` so they don't pin a connection forever.
- Don't hold a connection across an LLM/subprocess/network await — split into Tx-A (read), session-less await, Tx-C (write).

## Migrations (Alembic)

Schema changes go through Alembic. Generate with `--autogenerate`, review the diff before applying. Test migrations against a local DB before deploying:

```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1 && alembic upgrade head  # round-trip
```

## Memory facade

`backend/app/services/memory_facade.py` is the single retrieval contract — fan-in across mem0 / episodic / user / blocks. `local_handler.py` calls it at session start to seed the system prompt. Enable mem0 backend with `ZERO_MEMORY_USE_MEM0=1`.

Use the facade — don't hit mem0 / episodic stores directly from handlers.
