"""Fix-109 hermetic gap-batch tests (supervise DRIVE+COVERAGE, run 22407470).

Each test discriminates the OLD (buggy) behavior from the NEW (fixed) behavior
against the real service code — no DB / no live LLM.

Batch:
  IDX1 - vault dim guard tracked settings.embedding_dimension (768), not a
         hardcoded 1024 that rejected every real 768-dim vector (dense
         retrieval was silently BM25-only on both index + query sides).
  IDX2 - _index_file writes a file's chunks in ONE transaction (delete+insert),
         not a per-chunk commit that left a half-indexed file on a mid-loop crash.
  IDX3 - semantic_search(table="facts") includes learned_at (was dropped).
  C1   - email draft stuck in "sending" after a crash is re-claimable by approve().
  C2   - DND window with start == end means "no DND", not permanently ON.
"""

from __future__ import annotations

import types

import pytest


# ---------------------------------------------------------------------------
# IDX1 — index side: _embed_dim tracks settings.embedding_dimension
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idx1_indexer_embed_dim_tracks_settings(monkeypatch):
    from app.infrastructure.config import get_settings
    from app.services import vault_indexer_service as vix

    svc = vix.VaultIndexerService()
    expected = get_settings().embedding_dimension
    # The guard dim must equal the embedder's real output dim, NOT a hardcoded
    # 1024. (Old code: self._embed_dim = 1024 -> never equal to 768.)
    assert svc._embed_dim == expected
    assert svc._embed_dim != 1024 or expected == 1024

    # A vector at the embedder's real dim must PASS the guard (old 1024 guard
    # would have rejected a 768-dim vector and returned None).
    real_vec = [0.01] * expected

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return list(real_vec)

    monkeypatch.setattr(vix, "get_llm_client", lambda: _FakeClient())
    out = await svc._embed("hello vault")
    assert out is not None, "real-dim vector was rejected by the indexer guard"
    assert len(out) == expected


# ---------------------------------------------------------------------------
# IDX1 — query side: _embed_query accepts the embedder's real dim
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idx1_query_embed_accepts_real_dim(monkeypatch):
    from app.infrastructure.config import get_settings
    from app.services import vault_retrieval_service as vrx

    expected = get_settings().embedding_dimension
    real_vec = [0.02] * expected

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return list(real_vec)

    monkeypatch.setattr(vrx, "get_llm_client", lambda: _FakeClient())
    out = await vrx._embed_query("find me notes")
    assert out is not None, "real-dim query vector was rejected (dense search dead)"
    assert len(out) == expected

    # A genuinely-mismatched vector still rejects loudly (graceful BM25 fallback).
    class _BadClient:
        async def embed(self, text, max_retries=1):
            return [0.0] * (expected + 13)

    monkeypatch.setattr(vrx, "get_llm_client", lambda: _BadClient())
    assert await vrx._embed_query("mismatch") is None


# ---------------------------------------------------------------------------
# IDX2 — _index_file commits a file's chunks in ONE transaction
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idx2_index_file_single_commit(monkeypatch, tmp_path):
    from app.services import vault_indexer_service as vix

    commits = {"n": 0}
    added_rows: list = []

    class _FakeResult:
        def scalar_one_or_none(self):
            return None

    class _FakeSession:
        async def execute(self, *a, **k):
            return _FakeResult()

        def add_all(self, rows):
            added_rows.extend(rows)

        def add(self, row):
            added_rows.append(row)

        async def commit(self):
            commits["n"] += 1

    class _SessionCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vix, "get_session", lambda: _SessionCtx())

    svc = vix.VaultIndexerService()

    async def _fake_embed(text):
        return [0.01] * svc._embed_dim

    monkeypatch.setattr(svc, "_embed", _fake_embed)

    # A body that splits into multiple chunks (3 headings).
    body = "\n\n".join(f"# H{i}\n" + ("word " * 50) for i in range(3))
    raw = body.encode("utf-8")
    fp = tmp_path / "n.md"
    fp.write_bytes(raw)  # _index_file calls fp.stat() for mtime
    written = await svc._index_file(fp, "n.md", raw, "deadbeef" * 8)

    assert written >= 3, "expected multiple chunks for a multi-heading file"
    assert len(added_rows) == written
    # Atomicity: exactly ONE commit for the whole file (old code committed once
    # per chunk -> >=3 commits, leaving partial state recoverable mid-loop).
    assert commits["n"] == 1, f"expected 1 transaction, got {commits['n']} commits"


# ---------------------------------------------------------------------------
# IDX3 — semantic_search facts include learned_at
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idx3_semantic_search_facts_include_learned_at(monkeypatch):
    from app.services import knowledge_service as ks

    rows = [("f1", "likes coffee", "personal", 0.9, "voice", "2026-06-09T00:00:00")]

    class _FakeResult:
        def fetchall(self):
            return rows

    class _FakeSession:
        async def execute(self, *a, **k):
            return _FakeResult()

    class _SessionCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ks, "get_session", lambda: _SessionCtx())

    svc = ks.KnowledgeService()

    async def _fake_embed(q):
        return [0.0] * 8

    monkeypatch.setattr(svc, "_generate_embedding", _fake_embed)

    out = await svc.semantic_search("coffee", table="facts")
    assert out and isinstance(out[0], dict)
    assert "learned_at" in out[0], "facts result dropped learned_at"
    assert out[0]["learned_at"] == "2026-06-09T00:00:00"


# ---------------------------------------------------------------------------
# C1 — draft stuck in "sending" after a crash is re-claimable by approve()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c1_stale_sending_draft_reclaimed(monkeypatch, tmp_path):
    from app.services import email_draft_pool_service as dp

    store_path = tmp_path / "draft_pool.json"
    monkeypatch.setattr(dp, "POOL_PATH", store_path)

    pool = dp.EmailDraftPool()
    did = (await pool.add_draft(
        account_id="default", thread_id=None, to="x@example.com",
        subject="s", body="b", meta={},
    )).id

    # Force the draft into a stale "sending" state (process died mid-send): old
    # updated_at well past the stale window.
    store = pool._read()
    for r in store["drafts"]:
        if r["id"] == did:
            r["status"] = "sending"
            r["updated_at"] = dp._now() - (dp._SENDING_STALE_S + 60)
    pool._write(store)

    async def _fake_send(draft):
        return ("sent-msg-1", None)

    monkeypatch.setattr(pool, "_send", _fake_send)

    out = await pool.approve(did)
    assert out is not None
    # Re-claimed and actually sent (old code no-op'd on "sending" forever).
    assert out.status == "sent", f"stale sending draft not re-claimed: {out.status}"

    # A FRESH sending draft (just claimed by a concurrent approve) must still be
    # left alone — only stale ones re-claim.
    did2 = (await pool.add_draft(
        account_id="default", thread_id=None, to="y@example.com",
        subject="s2", body="b2", meta={},
    )).id
    store = pool._read()
    for r in store["drafts"]:
        if r["id"] == did2:
            r["status"] = "sending"
            r["updated_at"] = dp._now()  # fresh
    pool._write(store)
    out2 = await pool.approve(did2)
    assert out2 is not None and out2.status == "sending", "fresh sending draft wrongly re-claimed"


# ---------------------------------------------------------------------------
# C2 — DND zero-width window (start == end) means NO DND
# ---------------------------------------------------------------------------
def test_c2_dnd_zero_width_window_is_off():
    from app.services import attention_middleware as am

    mw = am.AttentionMiddleware()

    # start == end -> "no DND" (old fall-through `h>=start or h<end` was always True).
    mw._settings = types.SimpleNamespace(dnd_start_hour=0, dnd_end_hour=0)
    assert mw._in_dnd_now() is False
    mw._settings = types.SimpleNamespace(dnd_start_hour=22, dnd_end_hour=22)
    assert mw._in_dnd_now() is False

    # A real overnight window still gates (sanity: not every config returns False).
    mw._settings = types.SimpleNamespace(dnd_start_hour=0, dnd_end_hour=24)
    # 0->24 is start<end covering all hours -> always DND (valid full-day window).
    assert mw._in_dnd_now() is True
