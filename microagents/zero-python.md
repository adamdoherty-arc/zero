---
name: zero-python
type: rules
triggers: [python, fastapi, async, pydantic, structlog, backend]
agent: any
---

Zero's Python conventions (see CLAUDE.md for full rules):

- All I/O is async (`async def`, `await`) — never block the event loop.
- Domain logic lives in `services/`; routers in `routers/` are thin
  Pydantic-validated wrappers.
- Singletons use `@lru_cache()` — see `get_settings`, `get_llm_router`,
  `get_memory_tree`.
- Errors raise `HTTPException` from routers; services raise typed
  exceptions and let routers translate.
- Logging is structured: `structlog.get_logger(__name__)`. Never
  `print()`. Include event names like `subconscious_started`.
- Test isolation: services that touch the filesystem read `_DATA_DIR` at
  __init__ time (NOT as a default arg) so monkeypatch works.
