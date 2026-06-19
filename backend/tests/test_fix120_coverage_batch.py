"""Fix-120 coverage batch — retrieve/index/capture carried-lead regressions.

RTV-3/RTV-4: meeting hybrid-search merge treated incompatible score scales
(fulltext ts_rank ~0.0-0.1 vs semantic cosine-similarity ~0.6-0.95) as directly
comparable and, on dedup, kept the first (fulltext) copy of a segment that also
matched semantically — burying strong semantic hits. The fix min-max normalizes
each ranker to [0,1] before the single sort and keeps the higher-scored copy,
tagging it 'hybrid'.
"""

from app.services.meeting_search_service import MeetingSearchService


def _ft(mid, ts, score, speaker="A"):
    return {
        "meeting_id": mid, "meeting_title": "M", "snippet": "s",
        "score": score, "timestamp": ts, "speaker": speaker, "source": "fulltext",
    }


def _sem(mid, ts, score, speaker="A"):
    return {
        "meeting_id": mid, "meeting_title": "M", "snippet": "s",
        "score": score, "timestamp": ts, "speaker": speaker, "source": "semantic",
    }


def test_merge_rtv3_fulltext_not_buried_by_scale():
    """A top fulltext hit (tiny raw ts_rank) must not sink below every semantic
    hit purely because cosine scores are numerically larger."""
    svc = MeetingSearchService()
    ft = [_ft("m_ft", 1.0, 0.08), _ft("m_ft2", 2.0, 0.02)]
    sem = [_sem("m_se", 3.0, 0.91), _sem("m_se2", 4.0, 0.70)]

    merged = svc._merge_results(ft, sem, limit=10)

    # Top fulltext (0.08) normalizes to 1.0 and shares the top with top semantic,
    # instead of ranking below 0.70 as a raw-score sort would force.
    assert merged[0]["score"] == 1.0
    assert "m_ft" in {m["meeting_id"] for m in merged[:2]}
    # Weakest in each list normalizes to 0.0 and sinks.
    assert merged[-1]["score"] == 0.0
    # Scores stay in [0,1] for the frontend "% match" display.
    assert all(0.0 <= m["score"] <= 1.0 for m in merged)


def test_merge_rtv4_dedup_keeps_better_hybrid_copy():
    """A segment present in BOTH rankers dedups to one 'hybrid' entry carrying
    the higher (semantic) score, not the worse fulltext copy."""
    svc = MeetingSearchService()
    ft = [_ft("m1", 1.0, 0.05), _ft("m2", 2.0, 0.10)]    # m1 -> norm 0.0
    sem = [_sem("m1", 1.0, 0.90), _sem("m3", 3.0, 0.60)]  # m1 -> norm 1.0

    merged = svc._merge_results(ft, sem, limit=10)

    m1 = [r for r in merged if r["meeting_id"] == "m1"]
    assert len(m1) == 1                 # deduped to a single entry (RTV-4)
    assert m1[0]["source"] == "hybrid"  # both rankers surfaced it
    assert m1[0]["score"] == 1.0        # kept the better copy, not the 0.0 fulltext one


def test_merge_degenerate_single_result_normalizes_to_one():
    svc = MeetingSearchService()
    merged = svc._merge_results([_ft("only", 1.0, 0.03)], [], limit=10)
    assert len(merged) == 1
    assert merged[0]["score"] == 1.0


def test_merge_empty_inputs():
    svc = MeetingSearchService()
    assert svc._merge_results([], [], limit=10) == []
