---
paths: ["backend/**"]
---

# Backend-only patterns

These rules apply when editing files under `backend/`.

## Async everywhere

All I/O uses `async/await`. If you see a sync `requests` / `psycopg2` / `time.sleep` call in new code, replace it with the async equivalent (`httpx.AsyncClient`, `asyncpg`, `asyncio.sleep`). Sync stragglers in legacy code should be lifted on touch.

## Service pattern (thin routers)

Routers (`backend/app/routers/`) are thin wrappers — they parse input, call a service method, return the response. All domain logic lives in `backend/app/services/`. A router function longer than ~20 lines is a smell.

```python
# router (thin)
@router.post("/sprints")
async def create_sprint(payload: SprintCreate, svc: SprintService = Depends()):
    return await svc.create(payload)

# service (logic)
class SprintService:
    async def create(self, payload: SprintCreate) -> Sprint:
        ...  # validate, persist, emit events
```

## Pydantic validation

All request/response models validated through Pydantic. Validation errors at the boundary surface as 422s with structured fields — that's the contract the frontend expects. Don't pass raw dicts past the router boundary.

## `@lru_cache()` singletons

Settings, clients, and other process-wide singletons:

```python
from functools import lru_cache

@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

Inject via FastAPI `Depends(get_settings)` rather than calling at module import.

## Error handling

- Raise `HTTPException(status_code=..., detail=...)` for client-facing errors.
- Catch and re-raise with context — never bare `except: pass`.
- Log unexpected failures with `structlog` including request context.

```python
import structlog
logger = structlog.get_logger(__name__)

try:
    result = await svc.do_thing(x)
except SomeServiceError as e:
    logger.error("svc.failed", error=str(e), x=x)
    raise HTTPException(status_code=502, detail="upstream service unavailable")
```

## Session-across-await anti-pattern

Never keep an `AsyncSessionLocal` open across an LLM / subprocess / network await. Split into Tx-A (read), session-less await, Tx-C (write). Otherwise hourly Postgres idle-in-tx FATALs.

## Realtime / vLLM routing

Realtime config resolution lives in `backend/app/routers/reachy_realtime.py` `_enriched_config`. Don't sprinkle backend-pick logic across handlers — change it there.

## Testing

- Unit tests live next to services in `backend/tests/`.
- Use `pytest-asyncio` (`asyncio_mode=auto`).
- Mock external HTTP with `respx`, mock LLM clients with module-level fakes.
- Golden-set CI (carousel V2) must pass before merging carousel-pipeline changes.
