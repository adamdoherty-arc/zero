"""Reel scene planning + copy composition.

Turns one ``QuoteCard`` into a short narrative arc of ``ReelScene``s (hook →
build → quote → reveal → CTA), with per-scene on-screen text, a stock/AI image
query, motion, and durations that sum to the target length. Also composes the
caption + hashtags + CTA.

LLM-first with a deterministic fallback so the pipeline never blocks.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from app.models.reel import (
    CaptionAnimation,
    QuoteCard,
    ReelScene,
    SceneMotion,
    SceneRole,
    SUBNICHE_DEFAULT_MOOD,
)

logger = structlog.get_logger(__name__)


# Proven hook templates (fill-in by the LLM or fallback). Kept short.
HOOK_TEMPLATES = [
    "Read this when you feel like quitting.",
    "Nobody tells you this about {theme}.",
    "Save this for the hard days.",
    "If you only watch one thing today...",
    "This changed how I think about {theme}.",
    "The truth about {theme} nobody says out loud.",
]

CTA_TEMPLATES = [
    "Follow for daily {niche}.",
    "Save this. Read it tomorrow.",
    "Which line hit hardest? Comment below.",
    "Follow @ for your daily reminder.",
    "Share this with someone who needs it.",
]

_MOTION_CYCLE = [
    SceneMotion.KEN_BURNS_IN.value,
    SceneMotion.KEN_BURNS_OUT.value,
    SceneMotion.PAN_RIGHT.value,
    SceneMotion.PAN_LEFT.value,
]

# Stock-search seed terms per mood — used when the planner doesn't give one.
MOOD_IMAGE_QUERIES = {
    "epic": "dramatic mountain peak sunrise clouds cinematic",
    "calm": "calm misty forest soft light minimal",
    "hopeful": "golden hour horizon warm light open road",
    "dark": "moody dark storm clouds dramatic black",
    "intense": "stormy ocean waves power dramatic",
    "reflective": "quiet lake reflection fog still water",
    "uplifting": "sunbeams through clouds light rays sky",
}


def _niche_label(sub_niche: Optional[str]) -> str:
    return (sub_niche or "motivation").replace("_", " ")


def _clamp_durations(n: int, target: float) -> list[float]:
    """Distribute target seconds across n scenes; hook/CTA a touch shorter."""
    if n <= 0:
        return []
    base = target / n
    durs = [base] * n
    # Hook + CTA slightly shorter, redistribute to the middle (quote) scenes.
    if n >= 3:
        spare = 0.0
        for idx in (0, n - 1):
            cut = base * 0.25
            durs[idx] -= cut
            spare += cut
        mid = list(range(1, n - 1))
        for idx in mid:
            durs[idx] += spare / len(mid)
    return [round(max(2.0, min(d, 6.5)), 2) for d in durs]


def _split_quote(text: str, parts: int) -> list[str]:
    """Split a quote into ``parts`` readable phrase chunks for the middle scenes."""
    words = text.split()
    if parts <= 1 or len(words) <= parts:
        return [text]
    per = max(1, len(words) // parts)
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= per and len(chunks) < parts - 1:
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def _fallback_scenes(
    quote: QuoteCard, *, sub_niche: Optional[str], scene_count: int,
    target_duration_s: float, mood: str, cta_text: str,
) -> list[ReelScene]:
    n = max(3, min(scene_count, 7))
    durs = _clamp_durations(n, target_duration_s)
    img_q = MOOD_IMAGE_QUERIES.get(mood, MOOD_IMAGE_QUERIES["reflective"])
    theme = quote.theme or _niche_label(sub_niche)

    hook = HOOK_TEMPLATES[len(quote.text) % len(HOOK_TEMPLATES)].format(theme=theme)
    middle_count = n - 2
    quote_chunks = _split_quote(quote.text, max(1, middle_count))

    scenes: list[ReelScene] = []
    scenes.append(ReelScene(
        scene_num=1, role=SceneRole.HOOK, text=hook,
        caption_phrases=hook.split(), image_query=img_q, voiceover_text=hook,
        duration_s=durs[0], motion=_MOTION_CYCLE[0], template="reel_hook",
        caption_animation=CaptionAnimation.FADE,
    ))
    for i, chunk in enumerate(quote_chunks):
        sn = i + 2
        scenes.append(ReelScene(
            scene_num=sn, role=SceneRole.QUOTE, text=chunk,
            caption_phrases=chunk.split(), image_query=img_q, voiceover_text=chunk,
            duration_s=durs[min(sn - 1, len(durs) - 1)],
            motion=_MOTION_CYCLE[(sn - 1) % len(_MOTION_CYCLE)],
            template="reel_quote", caption_animation=CaptionAnimation.WORD_POP,
        ))
    scenes.append(ReelScene(
        scene_num=len(scenes) + 1, role=SceneRole.CTA, text=cta_text,
        caption_phrases=cta_text.split(), image_query=img_q, voiceover_text=cta_text,
        duration_s=durs[-1], motion=_MOTION_CYCLE[len(scenes) % len(_MOTION_CYCLE)],
        template="reel_cta", caption_animation=CaptionAnimation.FADE,
    ))
    # Renumber sequentially.
    for idx, sc in enumerate(scenes, start=1):
        sc.scene_num = idx
    return scenes


def _strip_json(raw: str) -> str:
    """Extract + repair a JSON array from an LLM response.

    Models routinely emit fenced blocks, trailing commas, and stray prose. We
    strip the fence, slice to the outermost ``[...]``, drop trailing commas, and
    normalise smart quotes so ``json.loads`` succeeds far more often (the
    deterministic planner still backstops a true parse failure).
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    s = m.group(0) if m else raw
    # Smart quotes → straight quotes.
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    # Drop trailing commas before } or ] (the #1 LLM JSON error).
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s


async def plan_scenes(
    quote: QuoteCard, *, sub_niche: Optional[str] = None, scene_count: int = 5,
    target_duration_s: float = 18.0, mood: Optional[str] = None,
    cta_text: Optional[str] = None, allow_llm: bool = True,
) -> list[ReelScene]:
    """Plan the scene arc for a reel. LLM-first, deterministic fallback."""
    mood = mood or quote.mood or SUBNICHE_DEFAULT_MOOD.get(sub_niche or "", "reflective")
    cta_text = cta_text or CTA_TEMPLATES[0].format(niche=_niche_label(sub_niche))

    if allow_llm:
        try:
            scenes = await _plan_scenes_llm(
                quote, sub_niche=sub_niche, scene_count=scene_count,
                target_duration_s=target_duration_s, mood=mood, cta_text=cta_text,
            )
            if scenes:
                return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning("reel_plan_scenes_llm_failed", error=str(exc))

    return _fallback_scenes(
        quote, sub_niche=sub_niche, scene_count=scene_count,
        target_duration_s=target_duration_s, mood=mood, cta_text=cta_text,
    )


async def _plan_scenes_llm(
    quote: QuoteCard, *, sub_niche: Optional[str], scene_count: int,
    target_duration_s: float, mood: str, cta_text: str,
) -> list[ReelScene]:
    from app.infrastructure.unified_llm_client import get_unified_llm_client

    client = get_unified_llm_client()
    niche = _niche_label(sub_niche)
    system = (
        "You are a world-class short-form video editor making motivation reels. "
        "Output ONLY a JSON array. Each element: "
        '{"role": "hook|quote|reveal|cta", "text": "on-screen text (<= 7 words, '
        'punchy, no quotes)", "image_query": "3-6 stock-footage search words", '
        '"voiceover": "what a narrator says"}. '
        "First scene is the hook (a scroll-stopper, not the quote). The quote is "
        "delivered across the middle scenes in readable chunks. Last scene is the CTA."
    )
    prompt = (
        f"Quote: \"{quote.text}\"\n"
        f"Author (only if verified, else omit): {quote.display_author}\n"
        f"Sub-niche: {niche}. Mood: {mood}.\n"
        f"Make exactly {scene_count} scenes for a ~{int(target_duration_s)}s reel. "
        f"CTA should be like: \"{cta_text}\".\n"
        "Return the JSON array now."
    )
    raw = await client.chat(
        prompt=prompt, system=system, task_type="reel_scene_plan",
        temperature=0.7, max_tokens=700,
    )
    data = json.loads(_strip_json(raw))
    if not isinstance(data, list) or not data:
        raise ValueError("planner returned non-list")

    n = len(data)
    durs = _clamp_durations(n, target_duration_s)
    fallback_q = MOOD_IMAGE_QUERIES.get(mood, MOOD_IMAGE_QUERIES["reflective"])
    role_map = {"hook": SceneRole.HOOK, "quote": SceneRole.QUOTE,
                "reveal": SceneRole.REVEAL, "cta": SceneRole.CTA, "build": SceneRole.BUILD}
    tmpl_map = {SceneRole.HOOK: "reel_hook", SceneRole.CTA: "reel_cta"}

    scenes: list[ReelScene] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        role = role_map.get(str(item.get("role", "quote")).lower(), SceneRole.QUOTE)
        text = str(item.get("text", "")).strip().strip('"')
        if not text:
            continue
        scenes.append(ReelScene(
            scene_num=i + 1, role=role, text=text,
            caption_phrases=text.split(),
            voiceover_text=str(item.get("voiceover", text)).strip() or text,
            image_query=str(item.get("image_query") or fallback_q).strip(),
            duration_s=durs[min(i, len(durs) - 1)],
            motion=_MOTION_CYCLE[i % len(_MOTION_CYCLE)],
            template=tmpl_map.get(role, "reel_quote"),
            caption_animation=CaptionAnimation.WORD_POP if role == SceneRole.QUOTE
            else CaptionAnimation.FADE,
        ))
    if not scenes:
        raise ValueError("no usable scenes parsed")
    for idx, sc in enumerate(scenes, start=1):
        sc.scene_num = idx
    return scenes


# ---------------------------------------------------------------------------
# Caption + hashtags
# ---------------------------------------------------------------------------

_NICHE_HASHTAGS = {
    "stoicism": ["#stoicism", "#stoic", "#marcusaurelius", "#discipline", "#mindset"],
    "discipline": ["#discipline", "#selfdiscipline", "#mindset", "#motivation", "#growth"],
    "wealth_mindset": ["#mindset", "#success", "#wealth", "#motivation", "#entrepreneur"],
    "self_improvement": ["#selfimprovement", "#growth", "#mindset", "#motivation", "#habits"],
    "faith": ["#faith", "#god", "#hope", "#christian", "#blessed"],
    "grindset": ["#grindset", "#hustle", "#discipline", "#motivation", "#nodaysoff"],
    "mental_health": ["#mentalhealth", "#healing", "#mindfulness", "#selfcare", "#growth"],
    "entrepreneurship": ["#entrepreneur", "#business", "#mindset", "#hustle", "#success"],
    "affirmations": ["#affirmations", "#selflove", "#mindset", "#growth", "#dailyreminder"],
}
_BASE_HASHTAGS = ["#motivation", "#inspiration", "#fyp", "#reels", "#shorts"]


def compose_caption(quote: QuoteCard, *, sub_niche: Optional[str], cta_text: str) -> tuple[str, list[str]]:
    """Compose a platform caption + hashtag set."""
    niche = sub_niche or quote.sub_niche or "motivation"
    author = ""
    if quote.attribution.value == "verified" and quote.author:
        author = f" — {quote.author}"
    caption = f"{quote.text}{author}\n\n{cta_text}"
    tags = _NICHE_HASHTAGS.get(niche, []) + _BASE_HASHTAGS
    # Dedup, keep order, cap at 8.
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return caption, out[:8]
