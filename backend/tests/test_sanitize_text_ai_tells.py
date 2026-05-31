"""Plan-88 — verify sanitize_text rewrites/strips common AI-tell phrases.

These cases are pinned: each represents a recurring phrase the Kimi/Qwen/GPT
outputs lean on at character-content density. If a future change removes
a substitution, this test fails so we re-think.
"""
from app.services.character_content_utils import sanitize_text


def test_em_dash_replaced_with_period_space():
    assert sanitize_text("Spider-Man—a hero") == "Spider-Man. a hero"


def test_in_conclusion_stripped():
    assert sanitize_text("In conclusion, he wins.") == "he wins."


def test_moreover_furthermore_additionally_stripped():
    assert sanitize_text("Moreover, he is strong.") == "he is strong."
    assert sanitize_text("Furthermore, she is brave.") == "she is brave."
    assert sanitize_text("Additionally, they are wise.") == "they are wise."


def test_delve_rewrites_to_explore_preserving_tense():
    assert "delve" not in sanitize_text("She delves into the topic.").lower()
    assert "explore" in sanitize_text("She delves into the topic.").lower()


def test_dive_into_rewrites_to_explore():
    assert "dive into" not in sanitize_text("He dives into the unknown.").lower()


def test_navigate_the_complexities_rewrites():
    out = sanitize_text("They navigate the complexities of duty.").lower()
    assert "navigate the" not in out


def test_pivotal_role_rewrites():
    out = sanitize_text("Iron Man plays a pivotal role in the MCU.")
    assert "pivotal role" not in out.lower()
    assert "matter" in out.lower()


def test_worth_noting_stripped():
    assert sanitize_text("It is worth noting that this matters.") == "this matters."
    assert sanitize_text("It's worth noting that this matters.") == "this matters."


def test_end_of_day_cliche_stripped():
    assert sanitize_text("At the end of the day, heroes win.") == "heroes win."


def test_in_the_world_of_rewritten():
    out = sanitize_text("In the world of Marvel, anything is possible.")
    assert out.startswith("In Marvel")


def test_plain_human_text_passes_unchanged():
    plain = "Normal sentence with no AI tells should pass."
    assert sanitize_text(plain) == plain


def test_em_dash_preserve_emphasis_path_still_strips():
    # The preserve_emphasis branch still removes em dashes and AI tells.
    out = sanitize_text(
        "**Bold**—In conclusion, **brave**.",
        preserve_emphasis=True,
    )
    assert "—" not in out
    assert "in conclusion" not in out.lower()
    assert "**" in out  # bold preserved


def test_idempotent_second_pass_is_noop():
    """Running sanitize twice gives the same result as once — important so
    pipeline retries don't accumulate damage."""
    src = "Moreover, she delves into the nuances of justice."
    once = sanitize_text(src)
    twice = sanitize_text(once)
    assert once == twice
