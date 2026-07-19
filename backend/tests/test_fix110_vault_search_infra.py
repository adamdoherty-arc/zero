"""Fix-110 — vault search-infra startup self-healer (content_tsv create_all-drift invariant).

Guards the Fix-109 silent-500 class: migration 056 adds vault_chunks.content_tsv
(BM25) + GIN/HNSW indexes, but SQLAlchemy create_all recreates the table without
them while alembic_version stays at 056, so the migration never re-runs and
EVERY vault search 500s on UndefinedColumn. ensure_vault_search_infra() re-asserts
the idempotent DDL on every startup; search_infra_status() surfaces drift in
/health/ready without a restart.

These tests are hermetic (mocked session). The decisive proof is the RUNTIME AC
run against the real pgvector DB in the deployed container — a mocked test cannot
catch a wrong pgvector assumption (the explicit Fix-109 lesson).
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import vault_retrieval_service as vrs


def _fake_session(row):
    sess = MagicMock()
    res = MagicMock()
    res.mappings.return_value.first.return_value = row
    sess.execute = AsyncMock(return_value=res)
    sess.commit = AsyncMock()
    return sess


def _patch_session(monkeypatch, sess):
    @asynccontextmanager
    async def _gs():
        yield sess

    monkeypatch.setattr(vrs, "get_session", _gs)


def test_repair_sql_includes_critical_content_tsv():
    """The repair set MUST (re)create the critical generated column + indexes."""
    joined = "\n".join(vrs._SEARCH_INFRA_REPAIR_SQL)
    assert "content_tsv tsvector" in joined
    assert "GENERATED ALWAYS AS" in joined
    assert "ix_vault_chunks_content_tsv" in joined
    assert "ix_vault_chunks_embedding_hnsw" in joined
    # All statements must be safe to re-run every boot.
    #
    # RET-02 (supervise zero 6a8c5562): the check below is a SYNTACTIC proxy for
    # that invariant ("IF NOT EXISTS" / "DO $$"). The de-dupe DELETE added with
    # RET-02 is idempotent by CONSTRUCTION rather than by keyword — re-running it
    # deletes nothing, because the duplicates it targets are gone after the first
    # pass. It is exempted explicitly (not by loosening the rule for everything)
    # so a genuinely non-idempotent statement still fails this test.
    _IDEMPOTENT_BY_CONSTRUCTION = ("DELETE FROM vault_chunks a USING vault_chunks b",)
    for stmt in vrs._SEARCH_INFRA_REPAIR_SQL:
        if stmt.startswith(_IDEMPOTENT_BY_CONSTRUCTION):
            continue
        s = stmt.upper()
        assert ("IF NOT EXISTS" in s) or ("DO $$" in s.replace(" ", "") or "DO $$" in s)
    # detect query inspects the critical column, not just indexes
    assert "content_tsv" in str(vrs._SEARCH_INFRA_DETECT_SQL)


@pytest.mark.asyncio
async def test_status_critical_when_content_tsv_missing(monkeypatch):
    _patch_session(monkeypatch, _fake_session({"has_tsv": 0, "has_gin": 0, "has_hnsw": 0}))
    st = await vrs.search_infra_status()
    assert st["status"] == "critical"  # BM25 would hard-500
    assert "vault_chunks.content_tsv" in st["missing"]
    assert st["content_tsv"] is False


@pytest.mark.asyncio
async def test_status_degraded_when_only_index_missing(monkeypatch):
    _patch_session(monkeypatch, _fake_session({"has_tsv": 1, "has_gin": 1, "has_hnsw": 0}))
    st = await vrs.search_infra_status()
    assert st["status"] == "degraded"  # perf only, not a 500
    assert st["missing"] == ["ix_vault_chunks_embedding_hnsw"]


@pytest.mark.asyncio
async def test_status_ok_when_all_present(monkeypatch):
    _patch_session(monkeypatch, _fake_session({"has_tsv": 1, "has_gin": 1, "has_hnsw": 1}))
    st = await vrs.search_infra_status()
    assert st["status"] == "ok"
    assert st["missing"] == []


@pytest.mark.asyncio
async def test_ensure_heals_and_runs_every_statement(monkeypatch):
    sess = _fake_session({"has_tsv": 0, "has_gin": 0, "has_hnsw": 0})
    _patch_session(monkeypatch, sess)
    out = await vrs.ensure_vault_search_infra()
    assert out["healed"] is True
    assert "vault_chunks.content_tsv" in out["missing_before"]
    # 1 vault detect + every repair statement + 1 episodic-HNSW detect (the
    # mocked scalar() is truthy, so the episodic repair itself doesn't run),
    # then a commit.
    assert sess.execute.await_count == 2 + len(vrs._SEARCH_INFRA_REPAIR_SQL)
    sess.commit.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_is_noop_when_all_present(monkeypatch):
    sess = _fake_session({"has_tsv": 1, "has_gin": 1, "has_hnsw": 1})
    _patch_session(monkeypatch, sess)
    out = await vrs.ensure_vault_search_infra()
    assert out["healed"] is False
    assert out["missing_before"] == []
    # still re-runs the idempotent DDL (cheap no-ops) every boot, plus the
    # vault + episodic detect probes
    assert sess.execute.await_count == 2 + len(vrs._SEARCH_INFRA_REPAIR_SQL)
