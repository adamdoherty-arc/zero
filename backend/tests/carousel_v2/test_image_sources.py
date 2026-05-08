"""Coverage for the 8 image source plugins + the curator orchestration."""

from __future__ import annotations

import pytest

# pytest-asyncio runs in mode=auto (see pytest.ini) so async functions are
# detected automatically. We don't apply a module-level mark — that would
# fire warnings on every sync test in the file.


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------

async def test_curator_drops_unknown_source_names_with_warning(monkeypatch):
    from app.services.image_curator_service import ImageCuratorService
    from app.services.image_sources.types import CandidateImage, ImageQuery

    svc = ImageCuratorService()

    async def _ok(query, *, limit):
        return [CandidateImage(source="tmdb", source_url="https://i/x.jpg")]

    svc._sources["tmdb"] = _ok  # override so we don't depend on real env

    out = await svc.curate(
        ImageQuery(character="Homelander", franchise="The Boys"),
        sources=["tmdb", "definitely_not_a_real_source"],
    )
    assert len(out) == 1
    assert out[0].source == "tmdb"


async def test_curator_dedupes_overlapping_urls(monkeypatch):
    from app.services.image_curator_service import ImageCuratorService
    from app.services.image_sources.types import CandidateImage, ImageQuery

    svc = ImageCuratorService()

    async def _a(query, *, limit):
        return [CandidateImage(source="tmdb", source_url="https://shared/url.jpg")]

    async def _b(query, *, limit):
        return [CandidateImage(source="fanart", source_url="https://shared/url.jpg")]

    svc._sources = {"tmdb": _a, "fanart": _b}
    out = await svc.curate(ImageQuery(character="x"))
    assert len(out) == 1


async def test_curator_failure_in_one_source_does_not_block_others(monkeypatch):
    from app.services.image_curator_service import ImageCuratorService
    from app.services.image_sources.types import CandidateImage, ImageQuery

    svc = ImageCuratorService()

    async def _broken(query, *, limit):
        raise RuntimeError("upstream rate-limited")

    async def _ok(query, *, limit):
        return [CandidateImage(source="fanart", source_url="https://i/y.jpg")]

    svc._sources = {"tmdb": _broken, "fanart": _ok}
    out = await svc.curate(ImageQuery(character="x"))
    assert len(out) == 1
    assert out[0].source == "fanart"


# ---------------------------------------------------------------------------
# TMDB plugin — franchise key normalization
# ---------------------------------------------------------------------------

async def test_tmdb_normalizes_underscored_franchise_and_falls_back_to_character(monkeypatch):
    """``the_boys`` must be searched as ``the boys`` so TMDB actually finds
    the show. If the franchise search returns no movie/tv hits, the plugin
    must fall back to the character name.
    """
    from app.services.image_sources import tmdb
    from app.services.image_sources.types import ImageQuery

    monkeypatch.setattr(tmdb, "_bearer", lambda: "fake-bearer")

    queries_seen: list[str] = []

    class _FakeResp:
        def __init__(self, payload):
            self._p = payload
        def json(self):
            return self._p
        def raise_for_status(self):
            return None

    class _FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_a):
            return None
        async def get(self, path, params=None):
            if path == "/search/multi":
                queries_seen.append(params["query"])
                # First call (franchise normalised) returns no movie/tv hits.
                # Second call (character) returns a TV id.
                if params["query"] == "the boys":
                    return _FakeResp({"results": [{"media_type": "person", "id": 999}]})
                if params["query"] == "Homelander":
                    return _FakeResp({"results": [{"media_type": "tv", "id": 76479}]})
                return _FakeResp({"results": []})
            if path.endswith("/images"):
                return _FakeResp({"backdrops": [{"file_path": "/p.jpg", "width": 1920, "height": 1080}]})
            return _FakeResp({})

    async def _client_factory():
        return _FakeClient()

    monkeypatch.setattr(tmdb, "_client", _client_factory)

    out = await tmdb.fetch(ImageQuery(character="Homelander", franchise="the_boys"), limit=5)
    assert "the boys" in queries_seen, "Franchise key must be normalized to 'the boys'"
    assert "Homelander" in queries_seen, "Must fall back to character name on miss"
    assert len(out) == 1
    assert out[0].source == "tmdb"


# ---------------------------------------------------------------------------
# Reddit URL resolution
# ---------------------------------------------------------------------------

def test_reddit_resolves_gallery_posts():
    from app.services.image_sources.reddit_praw import _resolve_image_urls

    post = {
        "is_gallery": True,
        "gallery_data": {"items": [{"media_id": "m1"}, {"media_id": "m2"}]},
        "media_metadata": {
            "m1": {"s": {"u": "https://preview.redd.it/m1.jpg?width=640&amp;auto=webp"}},
            "m2": {"s": {"u": "https://preview.redd.it/m2.png?auto=webp"}},
        },
    }
    urls = _resolve_image_urls(post)
    assert len(urls) == 2
    assert all("&" in u or "auto=" in u for u in urls)
    # &amp; was unescaped to &
    assert "&amp;" not in urls[0]


def test_reddit_skips_non_image_links():
    from app.services.image_sources.reddit_praw import _resolve_image_urls

    post = {"url_overridden_by_dest": "https://youtube.com/watch?v=xyz"}
    assert _resolve_image_urls(post) == []


def test_reddit_promotes_preview_to_i_redd_it():
    from app.services.image_sources.reddit_praw import _resolve_image_urls

    post = {"url_overridden_by_dest": "https://preview.redd.it/abc.jpg?width=1080&auto=webp"}
    urls = _resolve_image_urls(post)
    assert urls == ["https://i.redd.it/abc.jpg"]


# ---------------------------------------------------------------------------
# Wikimedia license filter
# ---------------------------------------------------------------------------

def test_wikimedia_license_filter_accepts_creative_commons():
    from app.services.image_sources.wikimedia import _license_ok

    assert _license_ok("CC-BY-SA 4.0") is True
    assert _license_ok("Public domain") is True
    assert _license_ok("CC0") is True
    assert _license_ok("CC BY") is True


def test_wikimedia_license_filter_rejects_non_free():
    from app.services.image_sources.wikimedia import _license_ok

    assert _license_ok("Fair use") is False
    assert _license_ok("Studio courtesy") is False
    assert _license_ok(None) is False
    assert _license_ok("") is False


# ---------------------------------------------------------------------------
# Empty-key short-circuits — every plugin returns [] when API key is unset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("module_name", [
    "fanart", "comicvine", "pexels", "unsplash",
])
async def test_source_returns_empty_when_keys_missing(module_name, monkeypatch):
    from importlib import import_module
    from app.services.image_sources.types import ImageQuery

    mod = import_module(f"app.services.image_sources.{module_name}")
    # Wipe whatever optional setting the plugin reads.
    from app.infrastructure.config import get_settings
    s = get_settings()
    for attr in ("fanart_api_key", "comicvine_api_key", "pexels_api_key", "unsplash_access_key"):
        if hasattr(s, attr):
            monkeypatch.setattr(s, attr, None)

    out = await mod.fetch(ImageQuery(character="x", title_id="tt0001"), limit=5)
    assert out == []


async def test_imdb_graphql_short_circuits_without_title_id():
    from app.services.image_sources import imdb_graphql
    from app.services.image_sources.types import ImageQuery

    # No title_id → no fetch attempted, returns [] immediately.
    out = await imdb_graphql.fetch(ImageQuery(character="x"), limit=5)
    assert out == []


async def test_reddit_returns_empty_without_oauth_keys(monkeypatch):
    from app.services.image_sources import reddit_praw
    from app.services.image_sources.types import ImageQuery

    async def _no_token():
        return None

    monkeypatch.setattr(reddit_praw, "_token", _no_token)
    out = await reddit_praw.fetch(ImageQuery(character="x"), limit=5)
    assert out == []
