"""
Regression tests for LangGraph orchestration graph.

Tests the two-tier classification system (keyword + LLM fallback),
graph compilation, routing, and new nodes (notion, money_maker).
"""
import pytest
from app.services.orchestration_graph import (
    classify_route_keywords,
    build_orchestration_graph,
    OrchestratorState,
    route_by_classification,
    VALID_ROUTES,
    KEYWORD_CONFIDENCE_THRESHOLD,
)


class TestClassifyRouteKeywords:
    """Test the Tier 1 keyword-based route classifier."""

    def test_sprint_route(self):
        route, score = classify_route_keywords("show active sprints")
        assert route == "sprint"
        assert score >= 1

    def test_email_route(self):
        route, score = classify_route_keywords("check my email inbox")
        assert route == "email"
        assert score >= 1

    def test_calendar_route(self):
        route, score = classify_route_keywords("what's on my schedule")
        assert route == "calendar"

    def test_enhancement_route(self):
        route, score = classify_route_keywords("scan for todo items to enhance")
        assert route == "enhancement"

    def test_briefing_route(self):
        route, score = classify_route_keywords("give me the daily briefing summary")
        assert route == "briefing"

    def test_research_route(self):
        route, score = classify_route_keywords("show research discoveries")
        assert route == "research"

    def test_notion_route(self):
        route, score = classify_route_keywords("check my notion workspace")
        assert route == "notion"

    def test_money_maker_route(self):
        route, score = classify_route_keywords("show me money making ideas for income")
        assert route == "money_maker"

    def test_general_fallback(self):
        route, score = classify_route_keywords("hello world")
        assert route == "general"
        assert score == 0

    def test_empty_string(self):
        route, score = classify_route_keywords("")
        assert route == "general"
        assert score == 0

    def test_multi_keyword_priority(self):
        route, score = classify_route_keywords("sprint task project backlog")
        assert route == "sprint"
        assert score >= 3  # High confidence

    def test_confidence_threshold(self):
        """High-confidence matches should exceed the threshold."""
        _, score = classify_route_keywords("sprint task project backlog velocity")
        assert score >= KEYWORD_CONFIDENCE_THRESHOLD


class TestRouteByClassification:
    """Test the conditional edge router."""

    def test_all_valid_routes(self):
        for route in VALID_ROUTES:
            state = {"route": route}
            assert route_by_classification(state) == route

    def test_invalid_route_defaults_to_general(self):
        state = {"route": "nonexistent"}
        assert route_by_classification(state) == "general"

    def test_missing_route_defaults_to_general(self):
        state = {}
        assert route_by_classification(state) == "general"


class TestGraphCompilation:
    """Test that the graph compiles successfully with all nodes."""

    def test_graph_compiles_without_checkpointer(self):
        graph = build_orchestration_graph(checkpointer=None)
        assert graph is not None

    def test_graph_compiles_with_memory_saver(self):
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        graph = build_orchestration_graph(checkpointer=checkpointer)
        assert graph is not None

    def test_state_schema(self):
        """Verify OrchestratorState has expected fields."""
        expected_keys = {"messages", "route", "context", "result"}
        assert set(OrchestratorState.__annotations__.keys()) == expected_keys

    def test_valid_routes_set(self):
        """Verify all expected routes are defined."""
        expected = {"sprint", "email", "calendar", "enhancement", "briefing",
                    "research", "notion", "money_maker", "general"}
        assert VALID_ROUTES == expected
