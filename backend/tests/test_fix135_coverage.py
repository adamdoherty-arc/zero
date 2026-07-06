"""Fix-135 coverage batch (supervise aba8c26e, 2026-07-06).

Dedicated unit tests for six previously-untested pure-logic methods in the
capture / learn / act-with-approval domains (the run's coverage priority).
These are deterministic, dependency-free helpers whose bugs would be silent:

- reachy_user_memory_service: `_cosine` (dedup similarity), `_tokens`
  (keyword-overlap fallback tokeniser), `_parse_notes_json` (tolerant LLM
  array extractor).
- email_classifier: `_keyword_classify` (the heuristic fallback used whenever
  the LLM classify call fails — the branch precedence is load-bearing).
- email_rule_service: `_match_value` (the core rule-condition matcher, incl.
  the invalid-regex guard) and `_parse_nested_json_from_llm` (the robust
  brace-balanced + fence-stripping extractor that `_execute_create_calendar_event`
  now routes through — see the parser consolidation in the same Fix-135 that
  removed the weaker flat-only `_parse_json_from_llm` duplicate).

The two class methods are exercised on bare instances (`object.__new__`) because
they read no instance state — this keeps them true unit tests with zero DB/LLM
init.
"""

from __future__ import annotations

import pytest

from app.services.reachy_user_memory_service import _cosine, _tokens, _parse_notes_json
from app.services.email_classifier import EmailClassifier
from app.services.email_rule_service import EmailRuleService
from app.models.email_rule import ConditionOperator


def _bare_classifier() -> EmailClassifier:
    """EmailClassifier instance without __init__ side effects; the methods
    under test read no instance state."""
    return object.__new__(EmailClassifier)


def _bare_rule_service() -> EmailRuleService:
    """EmailRuleService instance without __init__ side effects."""
    return object.__new__(EmailRuleService)


# --------------------------------------------------------------------------
# reachy_user_memory_service._cosine
# --------------------------------------------------------------------------
class TestCosine:
    def test_empty_returns_zero(self):
        assert _cosine([], [1.0]) == 0.0
        assert _cosine([1.0], []) == 0.0

    def test_mismatched_length_returns_zero(self):
        assert _cosine([1.0, 2.0], [1.0]) == 0.0

    def test_zero_norm_returns_zero(self):
        # a zero vector has no direction; guard must avoid div-by-zero
        assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_identical_vectors_is_one(self):
        assert _cosine([3.0, 4.0], [3.0, 4.0]) == pytest.approx(1.0)

    def test_orthogonal_is_zero(self):
        assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_is_negative_one(self):
        assert _cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_known_value(self):
        # a=[1,2], b=[2,1]: dot=4, |a|=|b|=sqrt(5) -> 4/5
        assert _cosine([1.0, 2.0], [2.0, 1.0]) == pytest.approx(4.0 / 5.0)


# --------------------------------------------------------------------------
# reachy_user_memory_service._tokens
# --------------------------------------------------------------------------
class TestTokens:
    def test_empty_returns_empty_set(self):
        assert _tokens("") == set()

    def test_drops_stopwords_keeps_content(self):
        assert _tokens("the quick brown fox") == {"quick", "brown", "fox"}

    def test_drops_short_tokens(self):
        # "i" stopword, "am"/"ok" len<=2 -> all dropped
        assert _tokens("I am OK") == set()

    def test_lowercases_and_dedupes(self):
        assert _tokens("Hello, HELLO world!") == {"hello", "world"}

    def test_all_stopwords_returns_empty(self):
        assert _tokens("what when where") == set()

    def test_alphanumeric_only(self):
        # punctuation split out; digit-runs kept if len>2
        assert _tokens("abc-123 !!!") == {"abc", "123"}


# --------------------------------------------------------------------------
# reachy_user_memory_service._parse_notes_json
# --------------------------------------------------------------------------
class TestParseNotesJson:
    def test_empty_returns_empty_list(self):
        assert _parse_notes_json("") == []

    def test_no_array_returns_empty(self):
        assert _parse_notes_json("no json here") == []

    def test_plain_array(self):
        assert _parse_notes_json('[{"text": "hi"}]') == [{"text": "hi"}]

    def test_strips_markdown_fences(self):
        assert _parse_notes_json('```json\n[{"text": "hi"}]\n```') == [{"text": "hi"}]

    def test_filters_non_dict_and_missing_text(self):
        raw = '[{"text": "a"}, {"nope": "b"}, "str", 5]'
        assert _parse_notes_json(raw) == [{"text": "a"}]

    def test_extracts_from_leading_prose(self):
        assert _parse_notes_json('Here you go: [{"text": "x"}] done') == [{"text": "x"}]

    def test_malformed_json_returns_empty(self):
        assert _parse_notes_json('[{"text": bad}]') == []


# --------------------------------------------------------------------------
# email_classifier._keyword_classify
# --------------------------------------------------------------------------
class TestKeywordClassify:
    def test_urgent(self):
        assert _bare_classifier()._keyword_classify("URGENT: server down", "a@b.com", "") == ("urgent", 0.85)

    def test_spam(self):
        assert _bare_classifier()._keyword_classify("You are a WINNER", "x@y.com", "click here now") == ("spam", 0.80)

    def test_newsletter_from_body(self):
        assert _bare_classifier()._keyword_classify("Weekly digest", "hi@news.com", "") == ("newsletter", 0.80)

    def test_newsletter_matches_from_address(self):
        # only the from-address carries the signal ("no-reply")
        assert _bare_classifier()._keyword_classify("Hello", "no-reply@x.com", "") == ("newsletter", 0.80)

    def test_important(self):
        assert _bare_classifier()._keyword_classify("Meeting tomorrow", "boss@co.com", "review the deadline") == ("important", 0.70)

    def test_urgent_beats_important_precedence(self):
        # urgent branch is checked before important; must win
        assert _bare_classifier()._keyword_classify("URGENT meeting invoice", "b@c.com", "") == ("urgent", 0.85)

    def test_normal_default(self):
        assert _bare_classifier()._keyword_classify("hello there", "friend@x.com", "how are you") == ("normal", 0.5)


# --------------------------------------------------------------------------
# email_rule_service._match_value
# --------------------------------------------------------------------------
class TestMatchValue:
    def test_contains_case_insensitive(self):
        assert _bare_rule_service()._match_value("Hello World", ConditionOperator.CONTAINS, "world", False) is True

    def test_contains_case_sensitive_negative(self):
        assert _bare_rule_service()._match_value("Hello World", ConditionOperator.CONTAINS, "world", True) is False

    def test_not_contains(self):
        assert _bare_rule_service()._match_value("abc", ConditionOperator.NOT_CONTAINS, "xyz", False) is True

    def test_exact_case_insensitive(self):
        assert _bare_rule_service()._match_value("ABC", ConditionOperator.EXACT, "abc", False) is True

    def test_starts_with(self):
        assert _bare_rule_service()._match_value("hello world", ConditionOperator.STARTS_WITH, "hello", False) is True

    def test_ends_with(self):
        assert _bare_rule_service()._match_value("hello world", ConditionOperator.ENDS_WITH, "world", False) is True

    def test_regex_valid(self):
        assert _bare_rule_service()._match_value("order #123", ConditionOperator.REGEX, r"#\d+", False) is True

    def test_invalid_regex_returns_false(self):
        # unbalanced char class -> re.error -> guarded to False, not a crash
        assert _bare_rule_service()._match_value("abc", ConditionOperator.REGEX, "a[", False) is False


# --------------------------------------------------------------------------
# email_rule_service._parse_nested_json_from_llm (consolidation target)
# --------------------------------------------------------------------------
class TestParseNestedJsonFromLlm:
    def test_flat_clean(self):
        assert _bare_rule_service()._parse_nested_json_from_llm('{"title": "X", "date": "2026-07-10"}') == {
            "title": "X",
            "date": "2026-07-10",
        }

    def test_flat_fenced(self):
        # the weaker _parse_json_from_llm we removed did NOT strip fences;
        # the robust parser this consolidates to does.
        assert _bare_rule_service()._parse_nested_json_from_llm('```json\n{"title": "X"}\n```') == {"title": "X"}

    def test_nested_object(self):
        # the removed flat parser's `\{[^{}]*\}` regex could not match this
        assert _bare_rule_service()._parse_nested_json_from_llm('{"a": {"b": 1}}') == {"a": {"b": 1}}

    def test_leading_prose(self):
        assert _bare_rule_service()._parse_nested_json_from_llm('Sure: {"title": "X"} ok') == {"title": "X"}

    def test_null_value(self):
        assert _bare_rule_service()._parse_nested_json_from_llm('{"title": null}') == {"title": None}

    def test_garbage_returns_none(self):
        assert _bare_rule_service()._parse_nested_json_from_llm("no json") is None
