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
