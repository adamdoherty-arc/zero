"""Caption + hashtag composer (carosel.txt §7 'Captions — 2026 formula').

Format::

  [HOOK ≤80 chars]
  [CONTEXT 1-2 lines]
  [VALUE 2-4 lines]
  [ENGAGEMENT PROMPT + 👇]
  [KEYWORDS — natural sentence with character names]
  [HASHTAGS — 5-9, separate block]

Hashtag stack: 3 broad + 3 niche + 3 ultra-niche pulled from the voice file
``hashtag_seed`` plus character/franchise tokens. Phase 6 wires shadow-ban
detection via TikTok Creative Center scrape.
"""

from __future__ import annotations

import re

from app.services.carousel_v2.voice_loader import load_voice


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def compose_hashtags(*, character: str, franchise: str | None, voice_key: str | None) -> list[str]:
    voice = load_voice(voice_key) if voice_key else {}
    seed = (voice.get("hashtag_seed") or {})
    out: list[str] = []
    for bucket in ("broad", "niche", "ultra"):
        for tag in seed.get(bucket) or []:
            if not tag.startswith("#"):
                tag = f"#{tag}"
            out.append(tag)
    char_slug = _slug(character)
    if char_slug:
        out.append(f"#{char_slug}")
    if franchise:
        f_slug = _slug(franchise)
        if f_slug and f"#{f_slug}" not in out:
            out.append(f"#{f_slug}")
    # Dedupe preserving order, cap to 9 (per blueprint)
    seen = set()
    final: list[str] = []
    for t in out:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        final.append(t)
        if len(final) >= 9:
            break
    return final


def compose_caption(
    *,
    hook: str,
    franchise: str | None,
    character: str,
    slide_summaries: list[str] | None = None,
    voice_key: str | None = None,
    engagement_prompt: str = "Which one shocked you?",
) -> str:
    """Returns the full caption block — TikTok captions don't honour line
    breaks via API, so we use ` · ` separators that read naturally inline.
    """
    parts: list[str] = []
    parts.append(hook[:80])
    if franchise:
        parts.append(f"From {franchise}.")
    if slide_summaries:
        bullets = " · ".join(s.strip() for s in slide_summaries[:3] if s)
        if bullets:
            parts.append(bullets)
    parts.append(f"{engagement_prompt} 👇")
    parts.append(f"More on {character} below.")
    tags = compose_hashtags(character=character, franchise=franchise, voice_key=voice_key)
    if tags:
        parts.append(" ".join(tags))
    caption = " ".join(parts)
    return caption[:2200]
