"""Fix-96 — hermetic unit tests for the supervise adversarial gap batch.

Covers the pure-logic fixes (no DB / network / LLM — all dependencies faked):
  #2 turn_outcome_service: outcome_learning bridge uses ``outcome.id`` (not the
     nonexistent ``turn_id``), so brain_outcome_record rows are no longer orphaned.
  #4 vault_indexer_service: ``_embed`` rejects dim != 1024 instead of silently
     zero-padding/truncating — symmetric with the Fix-93 query-side guard.
  #6 email_draft_pool_service: ``_send`` forwards ``account_id`` + ``thread_id``
     whenever the send method accepts them, never silently dropping routing,
     and never blind-retries a partially-executed send.
  #7 reachy_realtime/tools: ``_set_persona`` rejects an unknown persona instead
     of persisting a bogus profile id.

pytest.ini sets ``asyncio_mode = auto`` so plain ``async def`` tests run directly.
"""
from __future__ import annotations

import sys
import types


# --------------------------------------------------------------------------- #
# #2 — outcome_learning bridge must use outcome.id, not getattr(outcome,"turn_id")
# --------------------------------------------------------------------------- #
async def test_turn_outcome_bridge_uses_id_not_turn_id(monkeypatch, tmp_path):
    from app.services import turn_outcome_service as tos

    captured: dict = {}

    class _FakeOutcomeLearning:
        async def record_outcome(self, **kwargs):
            captured.update(kwargs)

    fake_mod = types.SimpleNamespace(
        get_outcome_learning_service=lambda: _FakeOutcomeLearning()
    )
    monkeypatch.setitem(sys.modules, "app.services.outcome_learning_service", fake_mod)
    # Keep the JSONL writer off the real workspace dir.
    monkeypatch.setattr(tos, "OUTCOME_DIR", tmp_path)
    monkeypatch.setattr(tos, "OUTCOME_PATH", tmp_path / "turns.jsonl")

    svc = tos.TurnOutcomeService()
    outcome = await svc.record_turn(
        persona_id="default",
        intent="voice",
        user_text="hi",
        assistant_text="hello",
    )

    assert outcome.id and outcome.id.startswith("turn-")
    # The bug: action_id used to be None (getattr for "turn_id" missed the real
    # field "id"). It must now equal the turn's real id.
    assert captured.get("action_id") == outcome.id
    assert captured.get("domain") == "voice"


# --------------------------------------------------------------------------- #
# #4 — indexer _embed rejects mismatched dim (index/retrieve symmetry)
# --------------------------------------------------------------------------- #
async def test_vault_indexer_embed_rejects_dim_mismatch(monkeypatch):
    from app.services import vault_indexer_service as vis

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return [0.1] * 512  # native dim != 1024

    monkeypatch.setattr(vis, "get_llm_client", lambda: _FakeClient())
    svc = vis.VaultIndexerService.__new__(vis.VaultIndexerService)
    svc._embed_dim = 1024

    out = await svc._embed("hello")
    assert out is None  # rejected loudly, NOT zero-padded to a garbage 1024-vec


async def test_vault_indexer_embed_accepts_correct_dim(monkeypatch):
    from app.services import vault_indexer_service as vis

    class _FakeClient:
        async def embed(self, text, max_retries=1):
            return [0.1] * 1024

    monkeypatch.setattr(vis, "get_llm_client", lambda: _FakeClient())
    svc = vis.VaultIndexerService.__new__(vis.VaultIndexerService)
    svc._embed_dim = 1024

    out = await svc._embed("hello")
    assert out is not None and len(out) == 1024


# --------------------------------------------------------------------------- #
# #6 — email _send forwards account_id + thread_id; legacy fallback never drops
#      routing silently nor double-sends
# --------------------------------------------------------------------------- #
def _draft(**over):
    base = dict(to="a@b.com", subject="s", body="b", account_id="acct-2",
                thread_id="thr-9", id="d1")
    base.update(over)
    return types.SimpleNamespace(**base)


async def test_email_send_forwards_account_and_thread(monkeypatch):
    from app.services import email_draft_pool_service as edps

    captured: dict = {}

    class _FakeGmail:
        async def send(self, *, to, subject, body, account_id=None, thread_id=None):
            captured.update(
                to=to, subject=subject, body=body,
                account_id=account_id, thread_id=thread_id,
            )
            return {"id": "msg-1"}

    monkeypatch.setitem(
        sys.modules, "app.services.gmail_service",
        types.SimpleNamespace(get_gmail_service=lambda: _FakeGmail()),
    )

    svc = edps.EmailDraftPool.__new__(edps.EmailDraftPool)
    msg_id, err = await svc._send(_draft())

    assert err is None and msg_id == "msg-1"
    assert captured["account_id"] == "acct-2"  # per-account routing preserved
    assert captured["thread_id"] == "thr-9"     # threading preserved


async def test_email_send_legacy_signature_no_silent_routing_drop(monkeypatch):
    from app.services import email_draft_pool_service as edps

    captured: dict = {}

    class _LegacyGmail:  # only send_email(to, subject, body) — no account/thread
        async def send_email(self, *, to, subject, body):
            captured.update(to=to, subject=subject, body=body)
            return {"id": "m2"}

    monkeypatch.setitem(
        sys.modules, "app.services.gmail_service",
        types.SimpleNamespace(get_gmail_service=lambda: _LegacyGmail()),
    )

    svc = edps.EmailDraftPool.__new__(edps.EmailDraftPool)
    msg_id, err = await svc._send(_draft())

    # No crash, no blind double-send; account/thread correctly NOT passed to a
    # method that can't accept them (the old code would TypeError + silently
    # resend from the default account).
    assert err is None and msg_id == "m2"
    assert "account_id" not in captured and "thread_id" not in captured


# --------------------------------------------------------------------------- #
# #7 — _set_persona validates against the known persona set
# --------------------------------------------------------------------------- #
async def test_set_persona_rejects_unknown(monkeypatch):
    from app.services.reachy_realtime import tools

    monkeypatch.setitem(
        sys.modules, "app.services.reachy_realtime.profiles",
        types.SimpleNamespace(list_profiles=lambda: [
            types.SimpleNamespace(id="assistant"),
            types.SimpleNamespace(id="companion"),
        ]),
    )

    res = await tools._set_persona(None, {"persona": "banana"}, None)
    assert "error" in res and "banana" in res["error"]
    assert "assistant" in res.get("valid_personas", [])


async def test_set_persona_accepts_known(monkeypatch):
    from app.services.reachy_realtime import tools

    monkeypatch.setitem(
        sys.modules, "app.services.reachy_realtime.profiles",
        types.SimpleNamespace(list_profiles=lambda: [
            types.SimpleNamespace(id="assistant"),
        ]),
    )
    captured: dict = {}
    monkeypatch.setitem(
        sys.modules, "app.services.reachy_realtime.config_store",
        types.SimpleNamespace(
            update_config=lambda d: (captured.update(d) or {"profile": d["profile"]})
        ),
    )

    res = await tools._set_persona(None, {"persona": "assistant"}, None)
    assert res.get("status") == "selected"
    assert captured.get("profile") == "assistant"
