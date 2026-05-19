"""Regression test for the 2026-05-15 silent-LLM-down bug.

We shipped the cockpit refactor declaring "robot moves" but never verified
that the active LLM provider was actually reachable. The Hyper-V firewall
was blocking Docker -> shared-bifrost on port 4445, so every Bifrost-Kimi
and Bifrost-Local-Qwen probe returned "Server disconnected without sending
a response," yet the realtime config still said `realtime_available: true`
and the UI happily showed "Start session."

These tests pin two invariants:

1. `/api/reachy-intent/providers/status` payload shape always includes
   `active_id` + `providers[].ok` so the UI can render a status without
   guessing.
2. The endpoint must reflect reality — when every probe fails, the
   response is allowed to come back all-down (and the UI banner picks
   it up), but the active provider must be in the providers list so
   the UI can name the failing provider.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _make_provider(id: str, label: str, provider: str = 'bifrost', model: str = 'x/y'):
    return SimpleNamespace(id=id, label=label, provider=provider, model=model)


def test_providers_status_payload_shape(client: TestClient, monkeypatch):
    """The endpoint must return active_id + providers[].ok so the UI banner
    knows which provider to name when it goes down."""

    import app.routers.reachy_intent as reachy_intent
    import app.services.reachy_chat_provider as chat_provider
    from app.routers.reachy_intent import ProviderStatus

    fake_providers = [
        _make_provider('bifrost-kimi', 'Bifrost Kimi K2.6', 'bifrost', 'moonshot/kimi-k2.6'),
        _make_provider('bifrost-local-qwen', 'Bifrost Local Qwen', 'bifrost', 'vllm-local/Qwen3-32B-AWQ'),
    ]
    monkeypatch.setattr(chat_provider, 'AVAILABLE_PROVIDERS', fake_providers)
    monkeypatch.setattr(chat_provider, 'get_active_provider_id', lambda: 'bifrost-kimi')

    async def _probe_ok(p):
        return ProviderStatus(
            id=p.id, label=p.label, provider=p.provider, model=p.model,
            ok=True, latency_ms=42.0, error=None, checked_at=0.0,
        )

    monkeypatch.setattr(reachy_intent, '_probe_single_provider', _probe_ok)
    # Bust the 15s probe cache so this test sees a fresh probe.
    monkeypatch.setattr(reachy_intent, '_providers_status_cache', None, raising=False)

    resp = client.get('/api/reachy-intent/providers/status')
    assert resp.status_code == 200

    body = resp.json()
    assert 'active_id' in body, 'UI needs active_id to name failing provider'
    assert 'providers' in body and isinstance(body['providers'], list)
    assert body['active_id'] == 'bifrost-kimi'

    ids = {p['id'] for p in body['providers']}
    assert 'bifrost-kimi' in ids
    assert 'bifrost-local-qwen' in ids

    for entry in body['providers']:
        assert {'id', 'label', 'provider', 'model', 'ok'} <= set(entry.keys())
        assert isinstance(entry['ok'], bool)


def test_providers_status_surfaces_all_down(client: TestClient, monkeypatch):
    """If every probe fails, the endpoint MUST tell the truth. This is the
    bug we shipped on 2026-05-15: realtime_available stayed true while every
    provider returned 'Server disconnected'."""

    import app.routers.reachy_intent as reachy_intent
    import app.services.reachy_chat_provider as chat_provider
    from app.routers.reachy_intent import ProviderStatus

    fake_providers = [
        _make_provider('bifrost-kimi', 'Bifrost Kimi K2.6', 'bifrost', 'moonshot/kimi-k2.6'),
        _make_provider('bifrost-local-qwen', 'Bifrost Local Qwen', 'bifrost', 'vllm-local/Qwen3-32B-AWQ'),
    ]
    monkeypatch.setattr(chat_provider, 'AVAILABLE_PROVIDERS', fake_providers)
    monkeypatch.setattr(chat_provider, 'get_active_provider_id', lambda: 'bifrost-kimi')

    async def _probe_down(p):
        return ProviderStatus(
            id=p.id, label=p.label, provider=p.provider, model=p.model,
            ok=False, latency_ms=None,
            error='Server disconnected without sending a response.',
            checked_at=0.0,
        )

    monkeypatch.setattr(reachy_intent, '_probe_single_provider', _probe_down)
    monkeypatch.setattr(reachy_intent, '_providers_status_cache', None, raising=False)

    resp = client.get('/api/reachy-intent/providers/status')
    assert resp.status_code == 200

    body = resp.json()
    providers = body.get('providers', [])
    assert len(providers) >= 1

    # The endpoint surfaces all-down honestly — the UI's LlmProviderBanner
    # depends on this to render its red strip.
    assert all(p['ok'] is False for p in providers), (
        f'All-down state must propagate to the UI; got: {providers}'
    )

    # The active provider must still be in the list so the banner can name it.
    active_id = body['active_id']
    assert any(p['id'] == active_id for p in providers), (
        f'active_id {active_id!r} not in providers list; UI cannot name failure'
    )
