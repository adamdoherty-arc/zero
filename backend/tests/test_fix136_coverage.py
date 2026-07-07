"""Fix-136 coverage batch.

Four groups:
1. RSN-9 regression — design_experiment list-return guard.
2. VaultRetrievalService.get_file — empty/multi-row/datetime paths.
3. ExperimentService.list_experiments — no-filter + filter WHERE clauses.
4. _json_safe — nested dict/date/tuple/set/scalar/mixed structure.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

import app.services.experiment_service as exp_svc
import app.services.vault_retrieval_service as vrs
from app.services.experiment_service import ExperimentService
from app.services.vault_indexer_service import _json_safe
from app.models.agent_company import ExperimentCreate, ExperimentType


# =====================================================================
# Helpers
# =====================================================================

def _make_exp_create(**overrides) -> ExperimentCreate:
    """Minimal valid ExperimentCreate."""
    defaults = dict(
        title="Test Experiment",
        hypothesis="X causes Y",
        experiment_type=ExperimentType.VALIDATION,
        parameters={},
    )
    defaults.update(overrides)
    return ExperimentCreate(**defaults)


class _FakeLLM:
    """Sequence-driven fake LLM client: pops one response per structured_chat call."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def structured_chat(self, **kw):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, **kw):
        return ""


class _FakeRow:
    """Minimal stand-in for an ExperimentModel ORM row."""

    def __init__(self, **kw):
        defaults = dict(
            id="exp-test",
            title="T",
            hypothesis="H",
            methodology="M",
            experiment_type="validation",
            status="designed",
            parameters={},
            metrics={},
            results=None,
            conclusion=None,
            linked_idea_id=None,
            linked_research_id=None,
            created_by_role="ceo",
            cost_usd=0.0,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            started_at=None,
            completed_at=None,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def _make_fake_session_factory(added_rows, returned_row=None):
    """Return a context-manager factory that fakes get_session().

    - ``added_rows`` is a list that will receive every add() call.
    - ``returned_row`` (optional): if set, ``session.refresh(row)`` writes
      all attributes from returned_row onto row (simulating a DB refresh).
    """

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def add(self, obj):
            added_rows.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            if returned_row is not None:
                for attr in vars(returned_row):
                    if not attr.startswith("_"):
                        setattr(obj, attr, getattr(returned_row, attr))

        async def execute(self, query, params=None):
            return _FakeResult([])

        async def get(self, model, pk, **kw):
            return None

    @asynccontextmanager
    async def _factory():
        yield _FakeSession()

    return _factory


class _FakeResult:
    """Fake execute() result with .mappings().all() and .scalars().all()."""

    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _make_session_factory_with_rows(rows):
    """Session factory whose execute() returns the given rows."""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, query, params=None):
            return _FakeResult(rows)

        def add(self, obj):
            pass

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    @asynccontextmanager
    async def _factory():
        yield _FakeSession()

    return _factory


# =====================================================================
# Group 1 — RSN-9: design_experiment list-return guard
# =====================================================================

async def test_design_experiment_list_response_uses_degraded_default(monkeypatch):
    """structured_chat returns a list -> degraded default applied, row persisted."""
    added = []

    # Session that records add() and exposes row attrs after refresh
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def add(self, obj):
            # Simulate DB giving the row a created_at so _orm_to_experiment works
            obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            obj.status = "designed"
            obj.results = None
            obj.conclusion = None
            obj.linked_idea_id = None
            obj.linked_research_id = None
            obj.created_by_role = "ceo"
            obj.cost_usd = 0.0
            obj.started_at = None
            obj.completed_at = None
            added.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(exp_svc, "get_session", _session_factory)

    svc = ExperimentService.__new__(ExperimentService)
    svc._llm = _FakeLLM([
        [{"methodology": "from list"}],  # list, not dict -> RSN-9 triggers
    ])

    result = await svc.design_experiment(_make_exp_create())

    assert len(added) == 1
    row = added[0]
    assert row.methodology == "Manual evaluation required"
    assert row.metrics == {}
    # Returned Experiment also reflects the degraded values
    assert result.methodology == "Manual evaluation required"


async def test_design_experiment_dict_response_passes_through(monkeypatch):
    """structured_chat returns a normal dict -> methodology passed through."""
    added = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def add(self, obj):
            obj.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            obj.status = "designed"
            obj.results = None
            obj.conclusion = None
            obj.linked_idea_id = None
            obj.linked_research_id = None
            obj.created_by_role = "ceo"
            obj.cost_usd = 0.0
            obj.started_at = None
            obj.completed_at = None
            added.append(obj)

        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(exp_svc, "get_session", _session_factory)

    svc = ExperimentService.__new__(ExperimentService)
    svc._llm = _FakeLLM([
        {"methodology": "real methodology", "metrics": {"acc": "accuracy"}, "success_criteria": "pass"},
    ])

    result = await svc.design_experiment(_make_exp_create())

    assert len(added) == 1
    row = added[0]
    assert row.methodology == "real methodology"
    assert row.metrics == {"acc": "accuracy"}
    assert result.methodology == "real methodology"


# =====================================================================
# Group 2 — VaultRetrievalService.get_file
# =====================================================================

async def test_get_file_empty_rows_returns_not_exists(monkeypatch):
    """No rows for path -> {path, exists: False}."""
    monkeypatch.setattr(vrs, "get_session", _make_session_factory_with_rows([]))

    svc = vrs.VaultRetrievalService.__new__(vrs.VaultRetrievalService)
    result = await svc.get_file("notes/missing.md")

    assert result == {"path": "notes/missing.md", "exists": False}


async def test_get_file_two_rows_assembles_content(monkeypatch):
    """2 rows -> content joined, chunk_count=2, tags from None -> []."""
    rows = [
        {"heading_path": "H1", "content": "A", "chunk_idx": 0,
         "frontmatter": None, "tags": None, "partition": "reference",
         "file_mtime": None},
        {"heading_path": "H2", "content": "B", "chunk_idx": 1,
         "frontmatter": None, "tags": None, "partition": "reference",
         "file_mtime": None},
    ]
    monkeypatch.setattr(vrs, "get_session", _make_session_factory_with_rows(rows))

    svc = vrs.VaultRetrievalService.__new__(vrs.VaultRetrievalService)
    result = await svc.get_file("notes/test.md")

    assert result["exists"] is True
    assert result["content"] == "A\n\nB"
    assert result["chunk_count"] == 2
    assert result["tags"] == []
    assert result["file_mtime"] is None
    assert result["partition"] == "reference"


async def test_get_file_datetime_mtime_becomes_isoformat(monkeypatch):
    """file_mtime as datetime -> isoformat string in result."""
    dt = datetime(2026, 3, 15, 10, 30, 0, tzinfo=timezone.utc)
    rows = [
        {"heading_path": "", "content": "body", "chunk_idx": 0,
         "frontmatter": {"title": "t"}, "tags": ["a", "b"],
         "partition": "journal", "file_mtime": dt},
    ]
    monkeypatch.setattr(vrs, "get_session", _make_session_factory_with_rows(rows))

    svc = vrs.VaultRetrievalService.__new__(vrs.VaultRetrievalService)
    result = await svc.get_file("journal/2026-03-15.md")

    assert result["file_mtime"] == dt.isoformat()
    assert result["frontmatter"] == {"title": "t"}
    assert result["tags"] == ["a", "b"]
    assert result["chunk_count"] == 1


# =====================================================================
# Group 3 — ExperimentService.list_experiments
# =====================================================================

async def test_list_experiments_no_filters_returns_mapped_list(monkeypatch):
    """No filters -> all rows returned, _orm_to_experiment applied."""
    rows = [
        _FakeRow(id="e1", title="E1"),
        _FakeRow(id="e2", title="E2"),
    ]

    captured_queries = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, query, params=None):
            captured_queries.append(query)
            return _FakeResult(rows)

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(exp_svc, "get_session", _session_factory)

    svc = ExperimentService.__new__(ExperimentService)
    results = await svc.list_experiments()

    assert len(results) == 2
    assert results[0].id == "e1"
    assert results[1].id == "e2"
    # No WHERE in base query (no filters applied)
    q_str = str(captured_queries[0])
    assert "WHERE" not in q_str


async def test_list_experiments_status_filter_adds_where_clause(monkeypatch):
    """status filter -> compiled query contains 'status'."""
    captured_queries = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, query, params=None):
            captured_queries.append(query)
            return _FakeResult([])

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(exp_svc, "get_session", _session_factory)

    svc = ExperimentService.__new__(ExperimentService)
    await svc.list_experiments(status="running")

    q_str = str(captured_queries[0])
    assert "status" in q_str.lower()


async def test_list_experiments_exp_type_filter_adds_where_clause(monkeypatch):
    """exp_type filter -> compiled query contains 'experiment_type'."""
    captured_queries = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def execute(self, query, params=None):
            captured_queries.append(query)
            return _FakeResult([])

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(exp_svc, "get_session", _session_factory)

    svc = ExperimentService.__new__(ExperimentService)
    await svc.list_experiments(exp_type="benchmark")

    q_str = str(captured_queries[0])
    assert "experiment_type" in q_str.lower()


# =====================================================================
# Group 4 — _json_safe
# =====================================================================

def test_json_safe_nested_dict_with_dates():
    """Nested dict with date values -> isoformat strings."""
    d = date(2026, 7, 7)
    dt = datetime(2026, 7, 7, 12, 0, 0)
    result = _json_safe({"day": d, "ts": dt, "nested": {"again": d}})
    assert result == {"day": "2026-07-07", "ts": "2026-07-07T12:00:00", "nested": {"again": "2026-07-07"}}


def test_json_safe_tuple_becomes_list():
    """Tuple input -> list output."""
    result = _json_safe((1, 2, 3))
    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_json_safe_set_becomes_list():
    """Set input -> list (order may vary, but all elements present)."""
    result = _json_safe({42})
    assert isinstance(result, list)
    assert 42 in result


def test_json_safe_non_str_dict_keys_become_str():
    """Non-str dict keys (int, date) -> str keys."""
    d = date(2026, 1, 1)
    result = _json_safe({1: "a", d: "b"})
    assert "1" in result
    assert str(d) in result


def test_json_safe_scalars_pass_through():
    """None, int, str, bool pass through unchanged."""
    assert _json_safe(None) is None
    assert _json_safe(42) == 42
    assert _json_safe("hello") == "hello"
    assert _json_safe(True) is True


def test_json_safe_nested_mixed_structure_json_serialisable():
    """Nested mixed structure (dict + list + date) is json.dumps-safe."""
    structure = {
        "items": [date(2026, 1, 1), {"k": datetime(2026, 2, 2, 0, 0, 0)}, (1, 2)],
        3: "int key",
    }
    safe = _json_safe(structure)
    # Must not raise
    encoded = json.dumps(safe)
    assert "2026-01-01" in encoded
    assert "2026-02-02" in encoded
    assert "int key" in encoded
