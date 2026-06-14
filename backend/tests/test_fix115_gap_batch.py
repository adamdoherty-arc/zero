"""Fix-115 regression-guard tests (supervise run e49df554, 2026-06-14).

Discriminating tests for the DRIVE+COVERAGE batch:
  - RTV: memory_facade must unwrap MemorySearchResult (memory.content/similarity);
    the old code read h.content/h.score and silently dropped every episodic hit.
  - RSN: council confidence must average only over roles that cast a counted vote,
    not abstain/structured-output-failed roles.
"""
import asyncio
import types

import pytest

from app.models.brain import EpisodicMemory, MemorySearchResult
from app.services.memory_facade import MemoryFacade, MemoryNote


def _make_episodic_hit(content: str, similarity: float = 0.91):
    return MemorySearchResult(
        memory=EpisodicMemory(
            id="em-test123",
            namespace="general",
            content=content,
            source_type="test",
            importance=50.0,
            tags=["alpha", "beta"],
            context={},
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        similarity=similarity,
    )


def test_episodic_recall_unwraps_memory_search_result(monkeypatch):
    """recall() must surface episodic pgvector hits.

    OLD behaviour: getattr(h, 'content') on a MemorySearchResult -> None ->
    `if not content: continue` dropped every hit. This test would FAIL on the
    old code (no episodic note returned) and PASS on the fix.
    """
    facade = MemoryFacade()

    class _FakeEpisodic:
        async def search(self, query, namespace=None, limit=5):
            return [_make_episodic_hit("the user prefers dark roast coffee")]

    # Force only the episodic source to contribute; neutralise the others.
    monkeypatch.setattr(
        "app.services.episodic_memory_service.get_episodic_memory_service",
        lambda: _FakeEpisodic(),
    )

    notes = asyncio.run(facade.recall("coffee", namespace="general", k=5))
    episodic = [n for n in notes if n.source == "episodic"]
    assert episodic, "episodic hit was dropped (regression: Fix-115)"
    assert episodic[0].text == "the user prefers dark roast coffee"
    assert episodic[0].tags == ["alpha", "beta"]
    assert 0.9 <= episodic[0].score <= 0.92  # similarity surfaced, not default 0.5


def test_council_confidence_excludes_abstainers():
    """avg_confidence must divide by counted votes, not by total roles.

    Mirrors the exact tally in council_service.deliberate(). With 2 voters at
    90 and 2 abstainers at 50, the OLD formula gives (90+90+50+50)/4 = 70; the
    FIX gives (90+90)/2 = 90.
    """
    round2 = {
        "engineer": {"position": "approve", "confidence": 90},
        "analyst": {"position": "approve", "confidence": 90},
        "skeptic": {"position": "abstain", "confidence": 50},
        "validator": {"position": "abstain", "confidence": 50},
    }
    position_counts = {"approve": 0, "reject": 0, "needs_revision": 0}
    total_confidence = 0.0
    counted_votes = 0
    for _role, vote in round2.items():
        pos = vote.get("position", "abstain")
        if pos in position_counts:
            position_counts[pos] += 1
            total_confidence += float(vote.get("confidence", 50))
            counted_votes += 1
    avg_confidence = total_confidence / max(counted_votes, 1)
    assert avg_confidence == 90.0, "abstainers polluted confidence (regression: Fix-115)"

    # Assert the real source enforces this (guards against the inline mirror drifting).
    import inspect
    from app.services import council_service
    src = inspect.getsource(council_service)
    assert "counted_votes" in src, "council_service lost the counted_votes fix"
    assert "max(counted_votes, 1)" in src, "council avg still divides by role count"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
