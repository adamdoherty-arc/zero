# Fix-NN: Ask Legion Chat Hang + Robustness

## Context

The "Ask Legion" employee chat at `/ask-legion` hangs for 10+ minutes when a message is sent. The user sees a spinner with no feedback. The root cause is that `chat_stream()` in [chat_service.py:849](backend/app/services/chat_service.py#L849) calls `_build_system_prompt()` **before** any SSE data is emitted. This method makes **7 sequential DB queries + 1 RAG search** with **zero timeouts**:

1. `_get_project_context()` -- 1 DB query
2. `_get_brain_context()` -- 5 sequential DB queries (brain decisions, self-improvement cycles, RCA clusters, health findings)
3. `_get_live_data_context()` -- 3 sequential DB queries (sprints, status aggregation, task breakdown)
4. `_get_rag_context()` -- Qdrant vector search (synchronous HTTP client, **blocks event loop**)

If any query stalls (DB lock contention, Qdrant timeout), the entire chat hangs indefinitely. The SSE endpoint has no timeout wrapper and no keepalive heartbeat.

**Secondary finding**: The ML pipeline technically picks up `ask_legion` calls (they're tracked with `_source="ask_legion"` and not in `LLM_EXEMPT_SOURCES`), but there's no specialized chat quality review, no learning injection into chat prompts, and no prompt evolution. The `legion-employee` skill benchmarks message counts, not response quality. These are **separate future sprints** (Employee-07+), not part of this fix.

---

## Plan: 5 Tasks

### Task 1: Parallelize `_build_system_prompt()` + add 30s outer timeout

**File**: [chat_service.py:679-705](backend/app/services/chat_service.py#L679-L705)

Replace 4 sequential `await` calls with `asyncio.gather(return_exceptions=True)` inside `asyncio.timeout(30)`:

```python
async def _build_system_prompt(self, query, session):
    parts = [LEGION_SYSTEM_PROMPT]
    t0 = time.monotonic()

    try:
        async with asyncio.timeout(30):
            results = await asyncio.gather(
                self._get_project_context(session.project_id),
                self._get_brain_context(),
                self._get_live_data_context(session.project_id),
                self._get_rag_context(query, session.project_id),
                return_exceptions=True,
            )
    except TimeoutError:
        logger.warning("[Chat] _build_system_prompt timed out after 30s")
        results = ["", "", "", ("", [])]

    # Unpack with graceful fallback for individual failures
    project_ctx = results[0] if not isinstance(results[0], BaseException) else ""
    brain_ctx = results[1] if not isinstance(results[1], BaseException) else ""
    live_ctx = results[2] if not isinstance(results[2], BaseException) else ""
    rag_result = results[3] if not isinstance(results[3], BaseException) else ("", [])
    rag_ctx, sources = rag_result if isinstance(rag_result, tuple) else ("", [])

    # Log failures + total elapsed
    for i, name in enumerate(["project", "brain", "live_data", "rag"]):
        if isinstance(results[i], BaseException):
            logger.warning(f"[Chat] Context {name} failed: {results[i]}")
    logger.info(f"[Chat] System prompt built in {time.monotonic() - t0:.2f}s")

    # Assemble (same as current)
    ...
```

**Impact**: Latency drops from sum(T1+T2+T3+T4) to max(T1,T2,T3,T4). Hard-capped at 30s.

---

### Task 2: Add per-method timeouts + timing logs to each context builder

**File**: [chat_service.py](backend/app/services/chat_service.py)

- `_get_brain_context()` (line 556): Wrap in `asyncio.timeout(10)`, add timing log
- `_get_live_data_context()` (line 463): Wrap in `asyncio.timeout(10)`, add timing log
- `_get_rag_context()` (line 403): Wrap call in `asyncio.wait_for(..., timeout=8)`, add timing log
- `_get_project_context()` (line 441): Add timing log only (already fast)

Each method already has individual try/except blocks, so these timeouts layer cleanly.

---

### Task 3: SSE keepalive + endpoint timeout + immediate status event

**File**: [chat.py:347-375](backend/app/api/endpoints/chat.py#L347-L375)

Three changes to the `/stream` endpoint:

**3a. Immediate "thinking" status event** -- Send `{"type": "status", "content": "Building context..."}` before entering the generator so the frontend knows we're alive:

```python
async def event_generator():
    yield f'data: {json.dumps({"type": "status", "content": "Building context..."})}\n\n'
    ...
```

**3b. SSE keepalive wrapper** -- New `_with_keepalive()` async generator that sends `: keepalive\n\n` (SSE comment) every 15s of silence:

```python
async def _with_keepalive(gen, interval=15.0):
    gen_iter = gen.__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(gen_iter.__anext__(), timeout=interval)
            yield chunk
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
        except StopAsyncIteration:
            break
```

Wrap the generator: `StreamingResponse(_with_keepalive(event_generator()), ...)`

**3c. Total endpoint timeout** -- 120s hard cap inside the generator. If exceeded, yield an error event and break.

---

### Task 4: Frontend handling of new events + reduced timeout

**Files**: [useChat.ts](frontend/src/hooks/useChat.ts), [AskLegion.tsx](frontend/src/pages/AskLegion.tsx)

- Handle `type: "status"` SSE event -- show "Building context..." indicator
- Clear status once first `type: "chunk"` arrives
- Reduce `STREAM_TIMEOUT` from 300s (5 min) to 120s (2 min) to match backend
- Skip SSE comments (lines starting with `:`) -- already handled by existing `if (!line.startsWith('data: '))` check
- Expose `statusMessage` from the hook

---

### Task 5: Qdrant client timeout in RAG service

**File**: [rag_service.py](backend/app/services/rag_service.py) (line ~126)

Add `timeout=5` to `QdrantClient()` constructor so individual search calls time out instead of blocking the event loop forever. This is the root fix for RAG hangs -- `asyncio.timeout` alone can't cancel synchronous HTTP calls.

---

## Timeout Budget

| Layer | Timeout | Caps |
|-------|---------|------|
| `_get_brain_context()` | 10s | 5 DB queries |
| `_get_live_data_context()` | 10s | 3 DB queries |
| `_get_rag_context()` | 8s | Embedding + Qdrant search |
| Qdrant per-request | 5s | Individual HTTP call |
| `_build_system_prompt()` | 30s | All 4 builders combined |
| SSE keepalive | 15s interval | Prevent proxy/frontend disconnect |
| Endpoint total | 120s | Entire request lifecycle |
| Frontend abort | 120s | Client-side safety net |

**Worst case**: 30s context + first chunk = ~35s. **Previous worst case**: infinite.

---

## ML Pipeline Coverage (NOT part of this fix, future sprints)

The existing ML pipeline has these gaps for Ask Legion:
1. No specialized chat quality criteria in LLM Review Agent
2. No learning injection (static system prompt, no episodic memory)
3. No chat prompt evolution via DSPy/GEPA canary system
4. `legion-employee` skill benchmarks quantity, not quality

**Recommendation**: Do NOT create a new skill. Instead, future Employee-07+ sprints should:
- Add `LEGION_SYSTEM_PROMPT` as a `prompt_templates` row for DSPy evolution
- Wire `learning_engine.enrich_task_context()` into chat context building
- Add chat-specific review criteria to LLM Review Agent
- Add response quality dimension to `legion-employee` skill benchmarks

These are additive -- they require the chat to be responsive first (this fix).

---

## Verification

1. Send a message on Ask Legion -- should respond in <30s (was hanging 10+ min)
2. Check backend logs for `[Chat] System prompt built in X.XXs` with all 4 context timings
3. Stop Qdrant container, send message -- should respond with no RAG context (not hang)
4. `curl -N` the stream endpoint -- see `: keepalive` comments every 15s during context phase
5. Frontend shows "Building context..." immediately, then clears when first chunk arrives
6. Docker rebuild both backend + frontend after changes
