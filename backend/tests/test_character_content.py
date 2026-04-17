"""
Tests for Character Content API endpoints.

Tests CRUD operations, stats, analytics, carousel management, research queue,
templates, music library, and auth enforcement for /api/characters/ endpoints.
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.character_content import (
    Character, CharacterCarousel, CharacterStats,
    CharacterImage, ResearchQueueStatus, ResearchJob,
    StoryTemplate, MusicTrack, ContentInspiration,
)
from app.routers.character_content import (
    SourceAnalytics, TemplateAnalytics, WinningPatterns,
    DeleteResponse,
)

# ---------------------------------------------------------------------------
# Auth token for protected endpoints
# ---------------------------------------------------------------------------
TEST_TOKEN = os.getenv("ZERO_GATEWAY_TOKEN", "test-token")
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def _make_character(**overrides) -> Character:
    defaults = dict(
        id="ch-abc123",
        name="Spider-Man",
        universe="marvel",
        franchise="MCU",
        real_name="Peter Parker",
        description="Friendly neighborhood hero",
        image_url="https://example.com/spidey.jpg",
        image_urls=["https://example.com/spidey.jpg"],
        research_data={"bio": "Peter Parker is Spider-Man"},
        research_status="completed",
        fact_bank=[{"text": "Spider-Man can stick to walls", "category": "powers", "surprise_score": 5}],
        tags=["superhero", "marvel"],
        posts_created=3,
        total_views=10000,
        total_likes=500,
        avg_engagement=5.0,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        last_researched=datetime(2026, 1, 1, tzinfo=timezone.utc),
        research_sources=["searxng", "fandom_wiki"],
        relationship_map={},
        research_depth_score=75.0,
        content_themes=["origin", "powers"],
    )
    defaults.update(overrides)
    return Character(**defaults)


def _make_carousel(**overrides) -> CharacterCarousel:
    defaults = dict(
        id="cc-xyz789",
        character_id="ch-abc123",
        character_name="Spider-Man",
        angle="hidden_truths",
        title="Spider-Man Hidden Truths",
        hook_text="Nobody talks about this...",
        slides=[
            {"slide_num": 1, "text": "Hook slide", "image_query": "spiderman cinematic"},
            {"slide_num": 2, "text": "1. Secret fact", "image_query": "spiderman web"},
        ],
        caption="Which fact surprised you? #SpiderMan",
        hashtags=["spiderman", "marvel", "fyp"],
        music_mood="epic",
        ai_review=None,
        ai_review_score=None,
        human_notes=None,
        status="draft",
        content_queue_id=None,
        publish_url=None,
        views=None,
        likes=None,
        comments=None,
        shares=None,
        saves=None,
        engagement_rate=None,
        created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        published_at=None,
        story_template=None,
        series_id=None,
        series_part=None,
        multi_character_ids=[],
        music_track=None,
        text_overlay_specs=[],
        brain_context_used=None,
        generation_metadata={},
    )
    defaults.update(overrides)
    return CharacterCarousel(**defaults)


def _make_stats(**overrides) -> CharacterStats:
    defaults = dict(
        total_characters=10,
        characters_researched=6,
        total_carousels=25,
        carousels_by_status={"draft": 10, "approved": 8, "published": 7},
        total_published=7,
        total_views=50000,
        total_likes=2500,
        avg_engagement_rate=5.0,
        top_characters=[{"name": "Spider-Man", "posts": 5, "likes": 1000}],
        top_angles=[{"angle": "hidden_truths", "count": 12}],
    )
    defaults.update(overrides)
    return CharacterStats(**defaults)


def _make_template(**overrides) -> StoryTemplate:
    defaults = dict(
        id="st-tmpl001",
        name="Secrets Revealed",
        template_type="secrets_revealed",
        description="Numbered list of shocking facts",
        slide_structure=[{"slide": 1, "role": "hook"}],
        prompt_template="Create a carousel about {name}",
        example_hook="5 Things They Don't Tell You...",
        suitable_angles=["hidden_truths"],
        suitable_universes=["marvel", "dc"],
        times_used=15,
        avg_score=8.2,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return StoryTemplate(**defaults)


def _make_music_track(**overrides) -> MusicTrack:
    defaults = dict(
        id="mt-track01",
        name="Epic Rise",
        artist="Cinematic Studio",
        mood="epic",
        energy_level="high",
        genre="cinematic",
        tiktok_sound_id=None,
        tiktok_sound_url=None,
        is_trending=False,
        trending_score=0.0,
        use_count=5,
        avg_engagement=7.5,
        tags=["epic", "hero"],
        metadata={},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MusicTrack(**defaults)


def _make_research_queue_status(**overrides) -> ResearchQueueStatus:
    defaults = dict(
        total_jobs=3,
        queued=1,
        researching=1,
        completed=1,
        failed=0,
        current_character="Spider-Man",
        current_step="searxng_search",
        jobs=[],
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        estimated_completion=None,
    )
    defaults.update(overrides)
    return ResearchQueueStatus(**defaults)


# ============================================================
# 1. CHARACTER CRUD (5 tests)
# ============================================================

class TestListCharacters:
    """GET /api/characters/ - list characters."""

    async def test_list_characters_returns_200(self, client):
        """List characters returns empty list when no characters exist."""
        mock_svc = AsyncMock()
        mock_svc.list_characters = AsyncMock(return_value=[])
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_characters_with_filters(self, client):
        """List characters applies universe and status filters."""
        char = _make_character()
        mock_svc = AsyncMock()
        mock_svc.list_characters = AsyncMock(return_value=[char])
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get(
                "/api/characters/?universe=marvel&status=active",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Spider-Man"
        assert data[0]["universe"] == "marvel"
        mock_svc.list_characters.assert_called_once_with(
            universe="marvel", status="active", research_status=None, limit=100,
        )


class TestCreateCharacter:
    """POST /api/characters/ - create a character."""

    async def test_create_character(self, client):
        """Create a new character returns 200 with character data."""
        char = _make_character(id="ch-new001")
        mock_svc = AsyncMock()
        mock_svc.create_character = AsyncMock(return_value=char)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/", json={
                "name": "Spider-Man",
                "universe": "marvel",
                "franchise": "MCU",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Spider-Man"
        assert data["id"] == "ch-new001"


class TestGetCharacter:
    """GET /api/characters/{id} - get single character."""

    async def test_get_character_found(self, client):
        """Get existing character returns 200 with full profile."""
        char = _make_character()
        mock_svc = AsyncMock()
        mock_svc.get_character = AsyncMock(return_value=char)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/ch-abc123", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "ch-abc123"
        assert data["research_status"] == "completed"
        assert len(data["fact_bank"]) == 1

    async def test_get_character_not_found(self, client):
        """Get nonexistent character returns 404."""
        mock_svc = AsyncMock()
        mock_svc.get_character = AsyncMock(return_value=None)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/ch-nonexistent", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        data = resp.json()
        # Custom exception handler wraps detail in error.message
        error_text = data.get("detail", "") or data.get("error", {}).get("message", "")
        assert "not found" in error_text.lower()


class TestUpdateCharacter:
    """PATCH /api/characters/{id} - update character."""

    async def test_update_character(self, client):
        """Update character returns 200 with updated data."""
        updated = _make_character(name="Spider-Man (Updated)", description="Updated description")
        mock_svc = AsyncMock()
        mock_svc.update_character = AsyncMock(return_value=updated)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.patch("/api/characters/ch-abc123", json={
                "description": "Updated description",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

    async def test_update_character_not_found(self, client):
        """Update nonexistent character returns 404."""
        mock_svc = AsyncMock()
        mock_svc.update_character = AsyncMock(return_value=None)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.patch("/api/characters/ch-missing", json={
                "name": "Anything",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 404


class TestDeleteCharacter:
    """DELETE /api/characters/{id} - delete character."""

    async def test_delete_character(self, client):
        """Delete character returns 200 with delete confirmation."""
        mock_svc = AsyncMock()
        mock_svc.delete_character = AsyncMock(return_value=True)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.delete("/api/characters/ch-abc123", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["id"] == "ch-abc123"

    async def test_delete_character_not_found(self, client):
        """Delete nonexistent character returns 404."""
        mock_svc = AsyncMock()
        mock_svc.delete_character = AsyncMock(return_value=False)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.delete("/api/characters/ch-nope", headers=AUTH_HEADERS)
        assert resp.status_code == 404


# ============================================================
# 2. STATS & ANALYTICS (3 tests)
# ============================================================

class TestGetStats:
    """GET /api/characters/stats - pipeline statistics."""

    async def test_get_stats(self, client):
        """Stats endpoint returns CharacterStats with all fields."""
        stats = _make_stats()
        mock_svc = AsyncMock()
        mock_svc.get_stats = AsyncMock(return_value=stats)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/stats", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_characters"] == 10
        assert data["characters_researched"] == 6
        assert data["total_carousels"] == 25
        assert data["total_published"] == 7
        assert "draft" in data["carousels_by_status"]
        assert len(data["top_characters"]) == 1
        assert len(data["top_angles"]) == 1


class TestSourceAnalytics:
    """GET /api/characters/analytics/sources - source breakdown."""

    async def test_source_analytics(self, client):
        """Source analytics returns source breakdown with fragment counts."""
        mock_svc = AsyncMock()
        mock_svc.get_source_analytics = AsyncMock(return_value={
            "sources": [
                {"source": "fandom_wiki", "fragment_count": 42, "avg_relevance": 0.78},
                {"source": "reddit", "fragment_count": 15, "avg_relevance": 0.65},
            ],
            "total_fragments": 57,
        })
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/analytics/sources", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_fragments"] == 57
        assert len(data["sources"]) == 2
        assert data["sources"][0]["source"] == "fandom_wiki"


class TestTemplateAnalytics:
    """GET /api/characters/analytics/templates - template usage."""

    async def test_template_analytics(self, client):
        """Template analytics returns leaderboard."""
        mock_tmpl_svc = AsyncMock()
        mock_tmpl_svc.get_template_leaderboard = AsyncMock(return_value={
            "templates": [
                {"name": "Secrets Revealed", "times_used": 20, "avg_score": 8.5},
            ],
        })
        with patch("app.routers.character_content.get_story_template_service", return_value=mock_tmpl_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/analytics/templates", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["templates"]) == 1
        assert data["templates"][0]["name"] == "Secrets Revealed"


# ============================================================
# 3. CAROUSEL MANAGEMENT (3 tests)
# ============================================================

class TestListCarousels:
    """GET /api/characters/carousels - list carousels."""

    async def test_list_carousels(self, client):
        """List carousels returns array with status and character info."""
        carousel = _make_carousel()
        mock_svc = AsyncMock()
        mock_svc.list_carousels = AsyncMock(return_value=[carousel])
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/carousels", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "cc-xyz789"
        assert data[0]["character_name"] == "Spider-Man"
        assert data[0]["status"] == "draft"

    async def test_list_carousels_with_filters(self, client):
        """List carousels applies status and character_id filters."""
        mock_svc = AsyncMock()
        mock_svc.list_carousels = AsyncMock(return_value=[])
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get(
                "/api/characters/carousels?status=approved&character_id=ch-abc123",
                headers=AUTH_HEADERS,
            )
        assert resp.status_code == 200
        mock_svc.list_carousels.assert_called_once_with(
            character_id="ch-abc123", status="approved", limit=50,
        )


class TestGenerateCarousel:
    """POST /api/characters/{id}/carousel - generate carousel."""

    async def test_generate_carousel(self, client):
        """Generate carousel returns new carousel data."""
        carousel = _make_carousel(status="draft")
        mock_svc = AsyncMock()
        mock_svc.generate_carousel = AsyncMock(return_value=carousel)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/ch-abc123/carousel", json={
                "angle": "hidden_truths",
                "slide_count": 6,
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["character_id"] == "ch-abc123"
        assert data["status"] == "draft"
        assert len(data["slides"]) == 2

    async def test_generate_carousel_no_research(self, client):
        """Generate carousel for unresearched character returns 400."""
        mock_svc = AsyncMock()
        mock_svc.generate_carousel = AsyncMock(
            side_effect=ValueError("Character has no research data. Run research first.")
        )
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/ch-noresearch/carousel", json={}, headers=AUTH_HEADERS)
        assert resp.status_code == 400
        data = resp.json()
        # Custom exception handler wraps detail in error.message
        error_text = data.get("detail", "") or data.get("error", {}).get("message", "")
        assert "research" in error_text.lower()


class TestApproveCarousel:
    """POST /api/characters/carousels/{id}/approve - approve carousel."""

    async def test_approve_carousel(self, client):
        """Approve carousel changes status to approved."""
        approved = _make_carousel(status="approved", human_notes="Looks great!")
        mock_svc = AsyncMock()
        mock_svc.approve_carousel = AsyncMock(return_value=approved)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/carousels/cc-xyz789/approve", json={
                "human_notes": "Looks great!",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["human_notes"] == "Looks great!"

    async def test_approve_carousel_not_found(self, client):
        """Approve nonexistent carousel returns 404."""
        mock_svc = AsyncMock()
        mock_svc.approve_carousel = AsyncMock(
            side_effect=ValueError("Carousel cc-missing not found")
        )
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/carousels/cc-missing/approve", json={}, headers=AUTH_HEADERS)
        assert resp.status_code == 404


# ============================================================
# 4. RESEARCH QUEUE (2 tests)
# ============================================================

class TestResearchQueue:
    """GET /api/characters/research-queue - queue status."""

    async def test_get_research_queue(self, client):
        """Research queue returns status with job details."""
        status = _make_research_queue_status()
        mock_svc = AsyncMock()
        mock_svc.get_research_queue_status = AsyncMock(return_value=status)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/research-queue", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_jobs"] == 3
        assert data["queued"] == 1
        assert data["researching"] == 1
        assert data["current_character"] == "Spider-Man"


class TestStartResearchQueue:
    """POST /api/characters/research-queue/start - start research."""

    async def test_start_research_queue(self, client):
        """Start research queue returns status with initiated jobs."""
        status = _make_research_queue_status(total_jobs=5, queued=5, researching=0, completed=0)
        mock_svc = AsyncMock()
        mock_svc.start_batch_research_async = AsyncMock(return_value=status)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/research-queue/start", json={
                "limit": 5,
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_jobs"] == 5
        assert data["queued"] == 5


# ============================================================
# 5. TEMPLATES & MUSIC (2 tests)
# ============================================================

class TestListTemplates:
    """GET /api/characters/templates - list story templates."""

    async def test_list_templates(self, client):
        """Templates endpoint returns list of story templates."""
        template = _make_template()
        mock_tmpl_svc = AsyncMock()
        mock_tmpl_svc.list_templates = AsyncMock(return_value=[template])
        with patch("app.routers.character_content.get_story_template_service", return_value=mock_tmpl_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/templates", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Secrets Revealed"
        assert data[0]["template_type"] == "secrets_revealed"
        assert data[0]["times_used"] == 15


class TestListMusic:
    """GET /api/characters/music - list music tracks."""

    async def test_list_music(self, client):
        """Music endpoint returns list of tracks."""
        track = _make_music_track()
        mock_music_svc = AsyncMock()
        mock_music_svc.get_tracks = AsyncMock(return_value=[track])
        with patch("app.routers.character_content.get_music_library_service", return_value=mock_music_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/music", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Epic Rise"
        assert data[0]["mood"] == "epic"

    async def test_list_music_with_mood_filter(self, client):
        """Music endpoint passes mood filter to service."""
        mock_music_svc = AsyncMock()
        mock_music_svc.get_tracks = AsyncMock(return_value=[])
        with patch("app.routers.character_content.get_music_library_service", return_value=mock_music_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/music?mood=dark", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        mock_music_svc.get_tracks.assert_called_once_with(mood="dark", limit=50)

    async def test_list_music_exposes_preview_url_field(self, client):
        """Music track responses expose the preview_url field (default null)."""
        track = _make_music_track()  # no preview_url supplied
        mock_music_svc = AsyncMock()
        mock_music_svc.get_tracks = AsyncMock(return_value=[track])
        with patch("app.routers.character_content.get_music_library_service", return_value=mock_music_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/music", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "preview_url" in data[0]
        assert data[0]["preview_url"] is None

    async def test_list_music_passes_through_preview_url(self, client):
        """Non-null preview_url is serialized through the response."""
        track = _make_music_track(preview_url="https://cdn.example.com/preview.mp3")
        mock_music_svc = AsyncMock()
        mock_music_svc.get_tracks = AsyncMock(return_value=[track])
        with patch("app.routers.character_content.get_music_library_service", return_value=mock_music_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/music", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["preview_url"] == "https://cdn.example.com/preview.mp3"


# ============================================================
# 6. AUTH ENFORCEMENT (2 tests)
# ============================================================

class TestAuthEnforcement:
    """Verify auth is required on character content endpoints."""

    async def test_no_auth_returns_401(self, client):
        """Request without auth token returns 401."""
        with patch("app.infrastructure.auth._get_api_token", return_value="real-secret"):
            resp = await client.get("/api/characters/stats")
        assert resp.status_code in (401, 403)

    async def test_wrong_token_returns_401(self, client):
        """Request with wrong auth token returns 401."""
        with patch("app.infrastructure.auth._get_api_token", return_value="real-secret"):
            resp = await client.get(
                "/api/characters/stats",
                headers={"Authorization": "Bearer wrong-token"},
            )
        assert resp.status_code == 401


# ============================================================
# 7. ADDITIONAL ENDPOINT COVERAGE (3 tests)
# ============================================================

class TestReviewQueue:
    """GET /api/characters/review-queue - carousels pending review."""

    async def test_review_queue(self, client):
        """Review queue returns list of pending carousels."""
        carousel = _make_carousel(status="pending_review")
        mock_svc = AsyncMock()
        mock_svc.list_review_queue = AsyncMock(return_value=[carousel])
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/review-queue", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending_review"


class TestRejectCarousel:
    """POST /api/characters/carousels/{id}/reject - reject carousel."""

    async def test_reject_carousel(self, client):
        """Reject carousel changes status and saves reason."""
        rejected = _make_carousel(status="rejected", human_notes="Inaccurate facts")
        mock_svc = AsyncMock()
        mock_svc.reject_carousel = AsyncMock(return_value=rejected)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/carousels/cc-xyz789/reject", json={
                "reason": "Inaccurate facts",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"


class TestGetSingleCarousel:
    """GET /api/characters/carousels/{id} - get specific carousel."""

    async def test_get_carousel(self, client):
        """Get carousel by ID returns full carousel data."""
        carousel = _make_carousel()
        mock_svc = AsyncMock()
        mock_svc.get_carousel = AsyncMock(return_value=carousel)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/carousels/cc-xyz789", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "cc-xyz789"
        assert data["hook_text"] == "Nobody talks about this..."

    async def test_get_carousel_not_found(self, client):
        """Get nonexistent carousel returns 404."""
        mock_svc = AsyncMock()
        mock_svc.get_carousel = AsyncMock(return_value=None)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.get("/api/characters/carousels/cc-missing", headers=AUTH_HEADERS)
        assert resp.status_code == 404


class TestCancelResearchQueue:
    """POST /api/characters/research-queue/cancel - cancel research."""

    async def test_cancel_research_queue(self, client):
        """Cancel research queue returns cancellation status."""
        mock_svc = AsyncMock()
        mock_svc.cancel_research_queue = AsyncMock(return_value={
            "status": "cancelled",
            "message": "Research queue cancelled",
        })
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.post("/api/characters/research-queue/cancel", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"


class TestUpdateCarousel:
    """PATCH /api/characters/carousels/{id} - edit carousel content."""

    async def test_update_carousel(self, client):
        """Update carousel hook text and caption."""
        updated = _make_carousel(hook_text="New hook!", caption="New caption")
        mock_svc = AsyncMock()
        mock_svc.update_carousel = AsyncMock(return_value=updated)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.patch("/api/characters/carousels/cc-xyz789", json={
                "hook_text": "New hook!",
                "caption": "New caption",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["hook_text"] == "New hook!"
        assert data["caption"] == "New caption"

    async def test_update_carousel_not_found(self, client):
        """Update nonexistent carousel returns 404."""
        mock_svc = AsyncMock()
        mock_svc.update_carousel = AsyncMock(return_value=None)
        with patch("app.routers.character_content.get_character_content_service", return_value=mock_svc), \
             patch("app.infrastructure.auth._get_api_token", return_value=TEST_TOKEN):
            resp = await client.patch("/api/characters/carousels/cc-nope", json={
                "hook_text": "Anything",
            }, headers=AUTH_HEADERS)
        assert resp.status_code == 404
