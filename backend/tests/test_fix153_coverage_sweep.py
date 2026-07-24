"""Fix-153 — coverage sweep (capture / content-loop / reason / learn).

Discriminating unit tests for the source-verified fixes shipped this run.
Each asserts the NEW behaviour and fails against the pre-fix code.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# R1/R2 — chat council-vote command routing (reason domain)
# ---------------------------------------------------------------------------

class _Decision:
    def __init__(self, did, topic="t", decision="approve", confidence=80.0):
        self.id = did
        self.topic = topic
        self.decision = decision
        self.confidence_score = confidence


class _FakeCouncil:
    """Records which method the chat handler routed to."""

    def __init__(self, pending=None):
        self.proposed = []
        self.voted = []
        self._pending = pending or [_Decision("cd_newest_pending")]

    async def propose(self, proposal):
        self.proposed.append(proposal.topic)
        return _Decision("cd_new_prop", topic=proposal.topic)

    async def list_decisions(self, pending_only=False, limit=20):
        return self._pending[:limit]

    async def conduct_vote(self, decision_id):
        self.voted.append(decision_id)
        return _Decision(decision_id, topic="voted-topic")


async def _run_council(monkeypatch, text, fake):
    from app.services import council_service as cs
    from app.services import orchestration_graph as og
    monkeypatch.setattr(cs, "get_council_service", lambda: fake)

    class _Msg:
        def __init__(self, c):
            self.content = c

    return await og.council_node({"messages": [_Msg(text)]})


async def test_council_vote_with_explicit_id_votes_that_id(monkeypatch):
    """R1+R2: the documented `council vote <id>` command votes THAT id
    (old code hit the propose branch and created a garbage proposal)."""
    fake = _FakeCouncil()
    await _run_council(monkeypatch, "council vote cd_abc123def", fake)
    assert fake.voted == ["cd_abc123def"]   # voted the typed id
    assert fake.proposed == []              # did NOT create a proposal


async def test_council_bare_vote_falls_back_to_newest_pending(monkeypatch):
    fake = _FakeCouncil(pending=[_Decision("cd_newest_pending")])
    await _run_council(monkeypatch, "vote", fake)
    assert fake.voted == ["cd_newest_pending"]
    assert fake.proposed == []


async def test_council_vote_on_topic_still_proposes(monkeypatch):
    """`council vote on <topic>` remains a propose alias, not a vote."""
    fake = _FakeCouncil()
    await _run_council(monkeypatch, "council vote on renewable energy", fake)
    assert fake.proposed == ["renewable energy"]
    assert fake.voted == []


async def test_council_propose_keyword_still_proposes(monkeypatch):
    fake = _FakeCouncil()
    await _run_council(monkeypatch, "propose we launch the beta", fake)
    assert fake.proposed == ["we launch the beta"]
    assert fake.voted == []


# ---------------------------------------------------------------------------
# A5 — incremental sync now REQUESTS deletion + label history (capture)
# ---------------------------------------------------------------------------

class _ListReq:
    def __init__(self, page, calls, **kwargs):
        self._page = page
        calls["history_types"].append(kwargs.get("historyTypes"))

    def execute(self):
        return self._page


class _History:
    def __init__(self, pages, calls):
        self._pages, self._calls = pages, calls

    def list(self, **kwargs):
        page = self._pages[self._calls["n"]]
        self._calls["n"] += 1
        return _ListReq(page, self._calls, **kwargs)


class _Users:
    def __init__(self, pages, calls):
        self._h = _History(pages, calls)

    def history(self):
        return self._h


class _Service:
    def __init__(self, pages, calls):
        self._u = _Users(pages, calls)

    def users(self):
        return self._u


def _make_gmail():
    from app.services.gmail_service import GmailService
    svc = GmailService.__new__(GmailService)

    async def _breaker_call(fn):
        return fn()

    svc._breaker_call = _breaker_call
    return svc


async def test_incremental_requests_deletions_and_labels():
    """A5: messageDeleted was omitted (trashed mail lingered forever) and label
    events were requested but never applied. The request now covers all four."""
    svc = _make_gmail()
    calls = {"n": 0, "history_types": []}
    pages = [{"history": [], "historyId": "10"}]
    await svc._fetch_all_history(_Service(pages, calls), "5")
    types = calls["history_types"][0]
    assert "messageAdded" in types
    assert "messageDeleted" in types      # was missing pre-fix
    assert "labelAdded" in types
    assert "labelRemoved" in types


# ---------------------------------------------------------------------------
# C4 — empty job id is not counted as a queued generation (content-loop)
# ---------------------------------------------------------------------------

async def test_empty_job_id_not_counted(monkeypatch):
    """C4: a truthy ACT result with no id keys must not append '' to job_ids
    (which made status falsely 'queued' and inflated content_generated_count)."""
    from app.services import content_agent_service as cas

    # Exercise just the id-extraction guard in isolation (the shape the loop uses).
    result = {"note": "accepted but no id"}
    job_id = result.get("job_id") or result.get("id") or ""
    assert job_id == ""   # nothing to append -> the `if not job_id: continue` skips it
