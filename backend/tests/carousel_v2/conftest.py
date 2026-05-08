"""Carousel V2 test fixtures.

Stub out heavy infra (Temporal, Postgres, Langfuse, Playwright) so the
tests run on a stock Python environment with only ``pytest``,
``pytest-asyncio``, ``pyyaml``, ``pydantic``, ``structlog`` and ``httpx``
installed. Each fixture is composable so individual tests can opt into a
real Postgres session by overriding ``patched_db``.
"""

from __future__ import annotations

import asyncio
import sys
import types
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Activity helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_temporal_module(monkeypatch):
    """Insert a minimal ``temporalio`` shim so activity modules import without
    the real SDK installed. The shim exposes ``activity.defn`` (a no-op
    decorator), ``activity.heartbeat`` (a no-op call), and ``workflow``
    placeholders not exercised by activity tests.
    """
    if "temporalio" in sys.modules:
        return

    fake = types.ModuleType("temporalio")
    activity_mod = types.ModuleType("temporalio.activity")
    workflow_mod = types.ModuleType("temporalio.workflow")
    common_mod = types.ModuleType("temporalio.common")

    def defn(*dargs, **dkw):
        # Support both ``@activity.defn`` and ``@activity.defn(name=...)``
        if dargs and callable(dargs[0]) and not dkw:
            return dargs[0]

        def _wrap(fn):
            return fn

        return _wrap

    activity_mod.defn = defn
    activity_mod.heartbeat = lambda *_a, **_kw: None

    workflow_mod.defn = defn
    workflow_mod.run = lambda fn: fn
    workflow_mod.signal = lambda fn=None: (fn if fn else lambda f: f)

    class _Unsafe:
        # Real Temporal SDK exposes ``workflow.unsafe.imports_passed_through()``
        # as a sync context manager. Match the real shape here so import-time
        # `with workflow.unsafe.imports_passed_through():` works under the stub.
        @staticmethod
        def imports_passed_through():
            class _Mgr:
                def __enter__(self_):
                    return None

                def __exit__(self_, *a):
                    return False

            return _Mgr()

    workflow_mod.unsafe = _Unsafe()
    common_mod.RetryPolicy = MagicMock

    fake.activity = activity_mod
    fake.workflow = workflow_mod
    fake.common = common_mod
    sys.modules["temporalio"] = fake
    sys.modules["temporalio.activity"] = activity_mod
    sys.modules["temporalio.workflow"] = workflow_mod
    sys.modules["temporalio.common"] = common_mod


@pytest.fixture
def workflow_ctx() -> dict[str, Any]:
    """A canonical workflow context dict shared between activities."""
    return {
        "generation_id": "gen-test-1",
        "topic": "Homelander",
        "franchise": "the_boys",
        "character_id": "char-test",
        "voice_file": "the_boys",
        "auto_publish": True,
        "input": {"slide_count": 5},
        "status": "researching",
    }


@pytest.fixture
def stub_unified_client(monkeypatch):
    """Stub the LLM router so judge / skeptic / designer activities never
    reach a real provider in tests.
    """
    from app.infrastructure import unified_llm_client as mod

    class _Stub:
        async def chat(self, *_a, **_kw):
            return ""

        async def structured_chat(self, prompt, **kw):
            schema = kw.get("output_schema")
            task = kw.get("task_type", "")
            # Hook writer / hook judge
            if task in {"hook_writer"}:
                return {"hook": "Homelander wasn't supposed to be the villain"}
            if task == "hook_judge":
                return {"index": 1}
            if task == "fact_verifier":
                return {"supported": True, "score": 0.9, "span": "matched"}
            if task == "skeptic":
                return [{
                    "claim": "Homelander wasn't supposed to be the villain",
                    "supporting_quote": "from the show",
                    "trap_category": None,
                    "verdict": "KEEP",
                    "rewrite_suggestion": None,
                }]
            if task.startswith("judge_"):
                return {"score": 8.0, "rationale": "anchored 4-7 range, clear hook"}
            if task == "designer":
                return [
                    {
                        "slide_num": 1,
                        "role": "hook",
                        "text": "Homelander wasn't supposed to be the villain",
                        "transition_to_next": "but here's why...",
                        "cited_fact_ids": [],
                    },
                    {
                        "slide_num": 2,
                        "role": "build",
                        "text": "Vought engineered him from infancy [fact_id:abc123]",
                        "transition_to_next": "and that's just the start",
                        "cited_fact_ids": ["abc123"],
                    },
                ]
            if isinstance(schema, list):
                return []
            if isinstance(schema, dict):
                return {k: v for k, v in (schema or {}).items()}
            return {}

    monkeypatch.setattr(mod, "UnifiedLLMClient", lambda: _Stub())
    return _Stub()


@pytest.fixture
def stub_db(monkeypatch):
    """Stub ``get_session`` so Postgres-backed services run without a DB.

    Each ``async with get_session() as session:`` block returns a
    ``MockSession`` that records ``add()`` calls and serves ``execute``
    results from a deque.
    """

    class _MockResult:
        def __init__(self, value=None):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

        def scalars(self):
            class _S:
                def __init__(self, v):
                    self._v = v

                def all(self):
                    return self._v if isinstance(self._v, list) else []

                def first(self):
                    return self._v[0] if isinstance(self._v, list) and self._v else self._v

            return _S(self._value)

        def all(self):
            return self._value if isinstance(self._value, list) else []

    class _MockSession:
        def __init__(self):
            self.added: list = []
            self.execute_results = []

        def add(self, obj):
            self.added.append(obj)

        async def execute(self, *_a, **_kw):
            if self.execute_results:
                return _MockResult(self.execute_results.pop(0))
            return _MockResult(None)

        async def flush(self):
            return None

        async def commit(self):
            return None

    session = _MockSession()

    @asynccontextmanager
    async def _get_session():
        yield session

    import app.infrastructure.database as dbmod
    monkeypatch.setattr(dbmod, "get_session", _get_session)
    return session


@pytest.fixture
def stub_vision(monkeypatch):
    """Stub vision_service so the image scorer's Stage 8 returns a deterministic
    JSON without hitting an LLM.
    """
    async def _describe(url, *, prompt="", json_mode=False):
        return {
            "character": "Homelander",
            "actor": "Antony Starr",
            "franchise": "The Boys",
            "likeness": 0.92,
            "is_promotional_still": False,
            "watermark": False,
            "text_overlay": False,
            "vertical_safe_crop_box": None,
            "_model": "stub-vision",
        }

    import app.services.vision_service as vs
    monkeypatch.setattr(vs, "describe_image_url", _describe, raising=False)
    return _describe
