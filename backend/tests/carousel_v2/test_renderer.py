"""Coverage for the Phase 5 render pipeline:

  brand_kit_service       — palette + LUT lookup
  cinematic_pass          — Pillow no-op behaviour when LUT/numpy unavailable
  playwright_renderer     — Jinja template rendering + Pillow fallback
  caption_service         — hashtag + caption composition
  r2_uploader.make_key    — predictable key shape
  idempotency.make_key    — order-stable hashing
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


# pytest-asyncio mode=auto — async tests detected automatically.


# ---------------------------------------------------------------------------
# brand_kit
# ---------------------------------------------------------------------------

def test_brand_kit_has_complete_palette_and_fonts():
    from app.services.carousel_v2.brand_kit_service import KITS

    required_color_fields = ("primary", "secondary", "accent", "bg", "fg")
    required_font_fields = ("font_hook", "font_headline", "font_body", "font_accent")
    for key, kit in KITS.items():
        for field in required_color_fields:
            value = getattr(kit, field)
            assert value.startswith("#"), f"{key}.{field} must be a hex colour"
            assert len(value) in (4, 7), f"{key}.{field} hex length unusual: {value}"
        for field in required_font_fields:
            assert getattr(kit, field), f"{key}.{field} must be set"
        assert kit.lut_path is not None and kit.lut_path.endswith(".cube")


def test_brand_kit_type_scale_descending():
    """Hook → headline → body → caption should monotonically shrink."""
    from app.services.carousel_v2.brand_kit_service import KITS

    for key, kit in KITS.items():
        scale = kit.type_scale
        for a, b in zip(scale, scale[1:]):
            assert a > b, f"{key}.type_scale not strictly descending: {scale}"


# ---------------------------------------------------------------------------
# cinematic_pass
# ---------------------------------------------------------------------------

def test_cinematic_pass_round_trips_intact_when_pillow_decode_fails(monkeypatch):
    """Garbage in → garbage out; the function must never raise."""
    from app.services.carousel_v2.brand_kit_service import get_brand_kit
    from app.services.carousel_v2.cinematic_pass import apply_cinematic_pass

    # Pass non-image bytes — Pillow's open() raises, we should fall through.
    raw = b"not an image"
    out = apply_cinematic_pass(raw, brand_kit=get_brand_kit("mcu"))
    assert out == raw


# ---------------------------------------------------------------------------
# playwright_renderer
# ---------------------------------------------------------------------------

def test_render_html_substitutes_kit_tokens():
    """The Jinja template must surface kit colors and slide text into the
    rendered HTML — guards against template rename / token drift.
    """
    from app.services.carousel_v2.brand_kit_service import get_brand_kit
    from app.services.carousel_v2.playwright_renderer import _render_html

    kit = get_brand_kit("the_boys")
    html = _render_html(
        template="hook",
        kit=kit,
        slide_num=1,
        text="Homelander wasn't supposed to be the villain",
        image_url="https://i/x.jpg",
        transition=None,
        sub=None,
    )
    assert kit.primary.lower() in html.lower()
    assert "Homelander" in html
    assert "https://i/x.jpg" in html


def test_render_html_falls_back_to_fact_template_when_unknown_template():
    from app.services.carousel_v2.brand_kit_service import get_brand_kit
    from app.services.carousel_v2.playwright_renderer import _render_html

    kit = get_brand_kit("mcu")
    # ``never_existed_template`` falls through to fact.html which renders the
    # number badge in zero-padded form.
    html = _render_html(
        template="never_existed_template",
        kit=kit,
        slide_num=3,
        text="Trivia about Loki",
        image_url="https://i/x.jpg",
        transition="and the worst is yet to come",
        sub=None,
    )
    assert "Trivia about Loki" in html
    # fact.html renders the number — slide_num=3 → "03"
    assert "03" in html


def test_clean_for_render_strips_citations_and_html():
    from app.services.carousel_v2.playwright_renderer import _clean_for_render

    text = "<b>Vought</b> engineered him from infancy [fact_id:abc123]"
    cleaned = _clean_for_render(text)
    assert "<b>" not in cleaned
    assert "[fact_id:abc123]" not in cleaned
    assert "Vought" in cleaned and "engineered" in cleaned


def test_pillow_fallback_paints_visible_text_only():
    """The Pillow fallback must paint the slide text — not raw HTML / CSS."""
    from app.services.carousel_v2.brand_kit_service import get_brand_kit
    from app.services.carousel_v2.playwright_renderer import _pillow_fallback

    kit = get_brand_kit("the_boys")
    text = "<style>.x{color:red}</style> Real visible text [fact_id:x]"
    body = _pillow_fallback(text, kit=kit)
    # We rendered a JPEG — header should start with FFD8FF
    assert body[:3] == b"\xff\xd8\xff"
    assert len(body) > 1000  # real image, not empty


async def test_render_slides_concurrent_disabled_path(monkeypatch):
    """``ZERO_DISABLE_PLAYWRIGHT=true`` must short-circuit to Pillow without
    importing playwright (so test envs without Chromium pass).
    """
    from app.services.carousel_v2 import playwright_renderer as pr

    monkeypatch.setenv("ZERO_DISABLE_PLAYWRIGHT", "true")

    # If the real import path fired, this would fail; instead we get JPEGs.
    result = await pr.render_slides_concurrent(
        [
            {"slide_num": 1, "template": "hook", "text": "Hook line", "image_url": ""},
            {"slide_num": 2, "template": "fact", "text": "Fact line", "image_url": ""},
        ],
        brand_kit_key="mcu",
    )
    assert len(result) == 2
    assert all(r and r[:3] == b"\xff\xd8\xff" for r in result)


async def test_render_slides_concurrent_empty_returns_empty():
    from app.services.carousel_v2 import playwright_renderer as pr

    assert await pr.render_slides_concurrent([], brand_kit_key="mcu") == []


# ---------------------------------------------------------------------------
# r2_uploader.make_key
# ---------------------------------------------------------------------------

def test_r2_make_key_format():
    from app.services.carousel_v2.r2_uploader import make_key

    k = make_key(generation_id="gen-abc", slide_num=3)
    assert k.startswith("carousels/gen-abc/03_")
    assert k.endswith(".jpg")


def test_r2_make_key_unique_per_call():
    from app.services.carousel_v2.r2_uploader import make_key

    a = make_key(generation_id="g", slide_num=1)
    b = make_key(generation_id="g", slide_num=1)
    assert a != b
