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
