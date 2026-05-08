"""Quality guards added 2026-04-28 after auditing 168 carousels:

  - 60+ ``mc-*`` carousels had 0 slides + template hooks because
    ``system_prompt=`` was a wrong kwarg (silently dropped).
  - 50-60% of slide images came from stock-photo aggregators / wallpaper
    farms / AI generators that almost never produce on-character content.
  - One ``cc-*`` carousel about A-Train (the speedster) was actually about
    A-Train III, a 1985 Japanese railroad simulation game — the research
    pipeline stored its own failure as facts with surprise_score=10.

These tests lock in the three guards that fix those failure modes.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Image host blocklist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.shutterstock.com/image-photo/random-12345.jpg",
    "https://static1.alamy.com/comp/abc/img.jpg",
    "https://www.dreamstime.com/something.jpg",
    "https://thumbs.dreamstime.com/b/12345.jpg",
    "https://imgcdn.stablediffusionweb.com/2024/x.jpg",
    "https://image.civitai.com/abc/x.jpg",
    "https://wallpapercave.com/wp/wp123.jpg",
    "https://wallpaperaccess.com/full/x.jpg",
    "https://wall.alphacoders.com/big.php?i=123",
    "https://img.freepik.com/free-photo/abc.jpg",
    "https://cdn.windowsreport.com/wp-content/x.jpg",
    "https://www.gettyimages.com/photo/abc-12345",
    "",
    None,
])
def test_blocked_hosts_are_rejected(url):
    from app.services.character_content_service import _is_blocked_image_host

    assert _is_blocked_image_host(url) is True


@pytest.mark.parametrize("url", [
    "https://image.tmdb.org/t/p/original/abc.jpg",
    "https://assets.fanart.tv/fanart/tv/12345/x.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/x.jpg",
    "https://i.redd.it/abc.png",
    "https://comicvine.gamespot.com/api/image/x.jpg",
    "https://m.media-amazon.com/images/M/abc.jpg",
])
def test_legitimate_hosts_pass(url):
    from app.services.character_content_service import _is_blocked_image_host

    assert _is_blocked_image_host(url) is False


# ---------------------------------------------------------------------------
# Failed-research fact-bank guard
# ---------------------------------------------------------------------------

def test_fact_bank_with_failure_sentinel_is_flagged():
    """The actual fact bank that produced the wrong-topic A-Train carousel."""
    from app.services.character_content_service import _fact_bank_is_failed_research

    bad_bank = [
        {
            "text": "No character information was retrieved. The search returned results for a Japanese video game series called A-Train (business simulation games from 1985) instead of the TV character from The Boys.",
            "source": "Search returned 0 results for TV character A-Train",
            "surprise_score": 10,
        },
        {
            "text": "The A-Train video game series began in 1985 and is one of the longest-running business simulation game franchises in Japan.",
            "source": "Research",
            "surprise_score": 9,
        },
    ]
    assert _fact_bank_is_failed_research(bad_bank) is True


def test_fact_bank_with_real_facts_passes():
    from app.services.character_content_service import _fact_bank_is_failed_research

    good_bank = [
        {
            "text": "Reggie Franklin was promoted to the Seven after Lamplighter retired.",
            "source": "The Boys S2 wiki",
            "surprise_score": 8,
        },
        {
            "text": "His Compound V dependency caused the heart attack that killed Popclaw's husband.",
            "source": "Episode S1E04",
            "surprise_score": 7,
        },
    ]
    assert _fact_bank_is_failed_research(good_bank) is False


def test_fact_bank_empty_is_not_flagged():
    """Empty fact bank is a different problem — the existing
    ``not char.fact_bank`` check handles it. The sentinel guard only fires
    on wrong-topic contamination.
    """
    from app.services.character_content_service import _fact_bank_is_failed_research

    assert _fact_bank_is_failed_research([]) is False
    assert _fact_bank_is_failed_research(None) is False


def test_fact_bank_mixed_string_and_dict_handled():
    from app.services.character_content_service import _fact_bank_is_failed_research

    mixed_bank = [
        "Could not find specific information about this character.",
        {"text": "Real fact #2", "surprise_score": 5},
    ]
    assert _fact_bank_is_failed_research(mixed_bank) is True


def test_only_top_three_facts_are_inspected():
    """Avoid false positives — if a fact bank has 50 real facts and one
    failure note buried at position #20, the guard shouldn't fire.
    """
    from app.services.character_content_service import _fact_bank_is_failed_research

    deep_bank = [
        {"text": f"Real fact #{i}", "surprise_score": 5}
        for i in range(1, 20)
    ] + [
        {"text": "No results found for some sub-query.", "surprise_score": 1},
    ]
    assert _fact_bank_is_failed_research(deep_bank) is False
