"""
Regression tests for LangGraph orchestration graph.

Sprint S68 Task #121: Verify LangGraph 1.0 API patterns are correct
and the orchestration graph compiles and routes properly.

These tests do NOT require external services (no Ollama, no Google APIs,
no PostgreSQL).
"""
import pytest
from app.services.orchestration_graph import (
    classify_route,
    build_orchestration_graph,
    OrchestratorState,
    route_by_classification,
)


class TestClassifyRoute:
    """Test the route classifier."""

    def test_sprint_route(self):
        assert classify_route("show active sprints") == "sprint"

    def test_email_route(self):
        assert classify_route("check my email inbox") == "email"

    def test_calendar_route(self):
        assert classify_route("what's on my schedule") == "calendar"

    def test_enhancement_route(self):
        assert classify_route("scan for todo items to enhance") == "enhancement"

    def test_briefing_route(self):
        assert classify_route("give me the daily briefing summary") == "briefing"

    def test_research_route(self):
        assert classify_route("show research discoveries") == "research"

    def test_general_fallback(self):
        assert classify_route("hello world") == "general"

    def test_empty_string(self):
        assert classify_route("") == "general"

    def test_multi_keyword_priority(self):
        # sprint has more keywords than others
        result = classify_route("sprint task project backlog")
        assert result == "sprint"


class TestRouteByClassification:
    """Test the conditional edge router."""

    def test_valid_routes(self):
        for route in ["sprint", "email", "calendar", "enhancement", "briefing", "research", "general"]:
            state = {"route": route}
            assert route_by_classification(state) == route

    def test_invalid_route_defaults_to_general(self):
        state = {"route": "nonexistent"}
        assert route_by_classification(state) == "general"

    def test_missing_route_defaults_to_general(self):
        state = {}
        assert route_by_classification(state) == "general"


class TestGraphCompilation:
    """Test that the graph compiles successfully."""

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
        # TypedDict should have these keys
        expected_keys = {"messages", "route", "context", "result"}
        assert set(OrchestratorState.__annotations__.keys()) == expected_keys
