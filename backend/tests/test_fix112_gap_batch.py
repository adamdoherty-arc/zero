"""Fix-112 regression guards.

1. learn_fact populates the user_facts.category_id FK (IDX4, carried 3 runs):
   the knowledge_categories table uses the slug as its primary key, so the
   resolver is a PK get with a slug-column fallback. Old code never set
   category_id, so these tests discriminate old vs new behavior.
2. providers/status probe timeout restored to 20s (the 40s llama.cpp
   rationale was retired by Infra-60's move to the vLLM gateway alias).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import knowledge_service as ks


class _FakeSession:
    def __init__(self, known_category_ids=(), slug_hit=None):
        self.known = set(known_category_ids)
        self.slug_hit = slug_hit
        self.added = []

    async def get(self, model, pk):
        if model is ks.KnowledgeCategoryModel:
            if pk in self.known:
                row = MagicMock()
                row.id = pk
                return row
            return None
        return MagicMock()  # profile row exists

    async def execute(self, _query):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.slug_hit
        return result

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def _session_ctx(session):
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return lambda: _Ctx()


@pytest.mark.asyncio
async def test_learn_fact_resolves_known_category_to_fk(monkeypatch):
    session = _FakeSession(known_category_ids={"general"})
    monkeypatch.setattr(ks, "get_session", _session_ctx(session))
    svc = ks.KnowledgeService()
    monkeypatch.setattr(svc, "_generate_embedding", AsyncMock(return_value=None))

    await svc.learn_fact("the sky is blue", category="general", source="test")

    facts = [o for o in session.added if isinstance(o, ks.UserFactModel)]
    assert len(facts) == 1
    assert facts[0].category_id == "general"
    assert facts[0].category == "general"


@pytest.mark.asyncio
async def test_learn_fact_unknown_category_keeps_fk_null(monkeypatch):
    session = _FakeSession(known_category_ids=set())
    monkeypatch.setattr(ks, "get_session", _session_ctx(session))
    svc = ks.KnowledgeService()
    monkeypatch.setattr(svc, "_generate_embedding", AsyncMock(return_value=None))

    await svc.learn_fact("x", category="no-such-category-xyz", source="test")

    facts = [o for o in session.added if isinstance(o, ks.UserFactModel)]
    assert len(facts) == 1
    assert facts[0].category_id is None
    assert facts[0].category == "no-such-category-xyz"


@pytest.mark.asyncio
async def test_learn_fact_falls_back_to_slug_lookup(monkeypatch):
    slug_row = MagicMock()
    slug_row.id = "resolved-by-slug"
    session = _FakeSession(known_category_ids=set(), slug_hit=slug_row)
    monkeypatch.setattr(ks, "get_session", _session_ctx(session))
    svc = ks.KnowledgeService()
    monkeypatch.setattr(svc, "_generate_embedding", AsyncMock(return_value=None))

    await svc.learn_fact("y", category="some-slug", source="test")

    facts = [o for o in session.added if isinstance(o, ks.UserFactModel)]
    assert facts[0].category_id == "resolved-by-slug"


def test_providers_status_probe_timeout_restored():
    from app.routers import reachy_intent

    assert reachy_intent._PROVIDERS_STATUS_PROBE_TIMEOUT <= 20.0


def test_router_config_defaults_mirror_infra60():
    """Code defaults must match the Infra-60 affinity lane (no retired
    kimi/minimax chains) so a fresh environment without the persisted
    workspace/llm/router_config.json doesn't boot into dead fallbacks."""
    from app.models.llm import LlmRouterConfig

    cfg = LlmRouterConfig()
    assert cfg.default_model == "bifrost/vllm-local/qwen3-chat"
    for task, assignment in cfg.task_assignments.items():
        specs = [assignment.model] + list(assignment.fallbacks or [])
        assert not any("kimi" in s or "MiniMax" in s for s in specs), (task, specs)
