"""
Shared utilities for the character content pipeline.

Extracted from character_content_service.py to reduce single-file LOC.
Contains: text sanitization, JSON parsing/repair, ID generation, hook
diversity checking, and ORM-to-Pydantic converters.
"""

import json
import re
import uuid
from typing import Any, Dict, List, Optional

import structlog

from app.db.models import (
    CharacterModel, CharacterCarouselModel, CharacterImageModel,
    CharacterCarouselVersionModel, MediaTitleModel, MediaImageModel,
)
from app.models.character_content import (
    Character, CharacterCarousel, CharacterImage, CarouselVersion,
)
from app.models.media_content import MediaTitle, MediaImage

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_id(prefix: str = "ch") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Text sanitization
# ---------------------------------------------------------------------------

def sanitize_text(text: str, preserve_emphasis: bool = False) -> str:
    """Strip AI-generated formatting: em dashes, markdown asterisks, en dashes.

    When preserve_emphasis is True, keep **bold** markers intact (used for
    slide/hook text rendered by the frontend with pill emphasis). Single
    *italic* markers are still stripped, and 3+ asterisks are normalized to 2.
    Multiple internal newlines are preserved (slide rhythm relies on them).
    """
    if not text:
        return text
    text = text.replace("\u2014", ". ")   # em dash
    text = text.replace("\u2013", "-")    # en dash -> hyphen
    if preserve_emphasis:
        # Normalize 3+ asterisks to 2, drop single *italic*
        text = re.sub(r'\*{3,}([^*]+)\*{3,}', r'**\1**', text)
        text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'\1', text)
    else:
        text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'\.\s*\.', '.', text)
    if preserve_emphasis:
        # Collapse runs of spaces/tabs but keep newlines for slide rhythm
        text = re.sub(r'[ \t]{2,}', ' ', text)
    else:
        text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Font style + accent color assignment (Phase 1.2/1.3)
# ---------------------------------------------------------------------------

# Words/patterns that signal a quote slide (Playfair italic).
_QUOTE_MARKS = ('"', '\u201c', '\u201d', "'", '\u2018', '\u2019')

# Numeric / stat detection for Bebas Neue wide-caps styling.
_STAT_PATTERN = re.compile(r'\b\d{1,4}(?:[.,]\d+)?(?:[%x]|k|m|b|\+)?\b', re.IGNORECASE)
_AGE_PATTERN = re.compile(r'\b(age\s+\d+|at\s+\d+|\d+\s+years?|\d+\s+yr)\b', re.IGNORECASE)

# 12-color palette, 3-4 hues per universe family, used for per-carousel
# randomization. Each universe gets a band of plausible hues to pick from.
UNIVERSE_PALETTE_BANDS: Dict[str, List[str]] = {
    "marvel":       ["#F87171", "#EF4444", "#FB923C", "#FCD34D"],
    "mcu":          ["#F87171", "#EF4444", "#FB923C", "#FCD34D"],
    "dc":           ["#A78BFA", "#8B5CF6", "#38BDF8", "#FDE047"],
    "dc comics":    ["#A78BFA", "#8B5CF6", "#38BDF8", "#FDE047"],
    "star_wars":    ["#FBBF24", "#FCD34D", "#EF4444", "#38BDF8"],
    "star wars":    ["#FBBF24", "#FCD34D", "#EF4444", "#38BDF8"],
    "anime":        ["#34D399", "#F472B6", "#FB7185", "#FCD34D"],
    "nintendo":     ["#38BDF8", "#A3E635", "#F87171", "#FDE047"],
    "gaming":       ["#38BDF8", "#A3E635", "#E879F9", "#2DD4BF"],
    "video games":  ["#38BDF8", "#A3E635", "#E879F9", "#2DD4BF"],
    "harry_potter": ["#FBBF24", "#991B1B", "#1E3A8A", "#A3E635"],
    "lotr":         ["#34D399", "#A78BFA", "#FBBF24", "#FB923C"],
    "tv":           ["#FB923C", "#E879F9", "#38BDF8", "#FB7185"],
    "film":         ["#FB923C", "#F87171", "#FCD34D", "#A78BFA"],
    "the boys":     ["#EF4444", "#7F1D1D", "#FCD34D", "#1E3A8A"],
}

# Fallback palette when universe is unknown.
UNIVERSE_PALETTE_DEFAULT = [
    "#FB923C", "#F87171", "#FBBF24", "#34D399",
    "#38BDF8", "#A78BFA", "#E879F9", "#FDE047",
    "#A3E635", "#2DD4BF", "#F472B6", "#EF4444",
]


def _seeded_rng(seed_text: str) -> "random.Random":
    import random as _random
    return _random.Random(seed_text)


def pick_accent_palette(
    universe: Optional[str], carousel_id: str
) -> Dict[str, Any]:
    """Pick a primary + secondary accent hex for a carousel.

    Deterministic on carousel_id so re-renders are stable, but varied across
    carousels so the same character gets a different palette each time.
    """
    import random as _random  # noqa: F401  (used by _seeded_rng)
    band = (
        UNIVERSE_PALETTE_BANDS.get((universe or "").lower())
        or UNIVERSE_PALETTE_DEFAULT
    )
    rng = _seeded_rng(f"palette:{carousel_id}")
    primary = rng.choice(band)
    # Secondary: pick a different color from the band if possible; else from
    # the default palette.
    alt_pool = [c for c in band if c != primary] or [
        c for c in UNIVERSE_PALETTE_DEFAULT if c != primary
    ]
    secondary = rng.choice(alt_pool)
    return {"primary": primary, "secondary": secondary}


def pick_slide_accent(
    palette: Dict[str, Any], carousel_id: str, slide_num: int
) -> str:
    """Pick the accent hex for a specific slide.

    Hook slide uses primary; subsequent slides alternate primary/secondary
    with a small random chance of swapping in a third color from the default
    palette so batches don't feel mechanical.
    """
    if slide_num <= 1:
        return palette["primary"]
    rng = _seeded_rng(f"slide:{carousel_id}:{slide_num}")
    # 75% pattern alternation, 25% wildcard
    if rng.random() < 0.75:
        return palette["primary"] if slide_num % 2 == 0 else palette["secondary"]
    wildcard_pool = [
        c for c in UNIVERSE_PALETTE_DEFAULT
        if c not in (palette["primary"], palette["secondary"])
    ]
    return rng.choice(wildcard_pool)


def pick_font_style_for_slide(
    slide_text: str,
    slide_index: int,
    hook_style: Optional[str] = None,
    is_hook_slide: bool = False,
) -> str:
    """Pick a Tailwind font-family key for a slide.

    Returns one of: display-hook, display-stat, display-quote, display-hot,
    display-shout, display-block, display-body.

    Rules:
      - Slide 0 / is_hook_slide with hot_take hook_style -> display-hot
      - Slide 0 / is_hook_slide with superlative/reveal -> display-shout
      - Slide 0 / is_hook_slide otherwise               -> display-hook
      - Body slide whose text is a quote                -> display-quote
      - Body slide heavy with stats/ages                -> display-stat
      - Body slide with a single short ALL-CAPS payoff  -> display-block
      - Otherwise                                       -> display-body
    """
    text = (slide_text or "").strip()

    if is_hook_slide or slide_index == 0:
        if hook_style == "hot_take":
            return "display-hot"
        if hook_style in ("superlative", "reveal"):
            return "display-shout"
        return "display-hook"

    # Quote detection: starts and ends with matching quote marks, or >60%
    # of the content is inside quotes.
    if text and text[0] in _QUOTE_MARKS and text[-1] in _QUOTE_MARKS:
        return "display-quote"

    # Stats-heavy slide: 2+ numeric tokens or an age reference.
    stat_hits = len(_STAT_PATTERN.findall(text))
    if stat_hits >= 2 or _AGE_PATTERN.search(text):
        return "display-stat"

    # Single short ALL-CAPS punch line.
    words = text.split()
    if 1 <= len(words) <= 5 and all(
        w.isupper() or not any(c.isalpha() for c in w) for w in words
    ):
        return "display-block"

    return "display-body"


# ---------------------------------------------------------------------------
# Slide text normalization (Phase 1.4)
# ---------------------------------------------------------------------------

# Do not split a line right after any of these tokens (possessive / conjunction
# mid-phrase breaks). Keys are the *previous* word's suffix/form.
_BAD_BREAK_TRAILING = {"'s", "'s,", "of", "to", "with", "and", "or", "the", "a", "an",
                       "for", "in", "on", "by", "at", "from", "into", "onto"}

# Do not split a line right before these tokens.
_BAD_BREAK_LEADING = {"and", "or", "to", "with", "of", "the", "a", "an",
                      "for", "in", "on", "by", "at", "from", "into", "onto",
                      "then"}


def normalize_slide_text(
    text: str,
    *,
    min_words: int = 6,
    max_words: int = 22,
    is_hook: bool = False,
) -> Dict[str, Any]:
    """Fix bad line breaks and measure density.

    Returns:
        {
          "text": cleaned text,
          "word_count": int,
          "too_thin": bool,
          "too_dense": bool,
          "fixed_breaks": int,   # how many bad breaks we merged inline
        }

    Rules:
      - If total word count <= 8, strip all newlines (inline).
      - If 9-14 words, allow at most 2 lines.
      - If 15+ words, allow up to 3 lines.
      - Never break after possessive 's or before conjunctions/prepositions.
    """
    if not text:
        return {"text": "", "word_count": 0, "too_thin": True,
                "too_dense": False, "fixed_breaks": 0}

    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    total_words = sum(len(ln.split()) for ln in lines)

    # Inline rule for short text
    if total_words <= 8:
        cleaned = " ".join(lines)
        return {
            "text": cleaned,
            "word_count": total_words,
            "too_thin": total_words < min_words and not is_hook,
            "too_dense": False,
            "fixed_breaks": max(0, len(lines) - 1),
        }

    # Merge bad breaks
    fixed = 0
    merged: List[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        if i + 1 < len(lines):
            last_word = current.split()[-1].lower() if current.split() else ""
            next_first = lines[i + 1].split()[0].lower() if lines[i + 1].split() else ""
            if last_word in _BAD_BREAK_TRAILING or next_first in _BAD_BREAK_LEADING:
                current = f"{current} {lines[i + 1]}"
                fixed += 1
                i += 2
                merged.append(current)
                continue
        merged.append(current)
        i += 1

    # Cap line count
    max_lines = 2 if total_words <= 14 else 3
    if len(merged) > max_lines:
        # Collapse trailing lines into the last allowed one
        head = merged[: max_lines - 1]
        tail = " ".join(merged[max_lines - 1:])
        merged = head + [tail]

    cleaned = "\n".join(merged)
    return {
        "text": cleaned,
        "word_count": total_words,
        "too_thin": total_words < min_words and not is_hook,
        "too_dense": total_words > max_words,
        "fixed_breaks": fixed,
    }


# ---------------------------------------------------------------------------
# Phrase-level carousel dedup (Phase 1.5)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9']+")


def trigram_set(text: str) -> set:
    """Build a set of 3-word shingles from text for phrase-level comparison."""
    words = _WORD_RE.findall((text or "").lower())
    if len(words) < 3:
        return set()
    return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}


def phrase_overlap_ratio(a: str, b: str) -> float:
    """Jaccard trigram overlap between two pieces of text. 0..1."""
    ta = trigram_set(a)
    tb = trigram_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# JSON parsing and repair
# ---------------------------------------------------------------------------

def parse_json_response(raw: str, context: str = "") -> Any:
    """Extract and parse JSON from LLM response text, handling truncation.

    Robust against:
      - ``<think>...</think>`` reasoning blocks (Qwen / Kimi)
      - Prose prefixes that contain stray braces (e.g. ``{example: foo}``)
        followed by the real JSON answer further down
      - Markdown ``​​​`` code fences
      - Trailing commas
      - Truncated JSON (closing braces missing)
    """
    raw = raw.strip()
    # Strip <think>...</think> tags (qwen + Kimi reasoning output)
    raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown code fence — most reliable when the LLM wrapped its answer
    json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', raw)
    if json_match:
        candidate = json_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Find balanced JSON object or array — walk every ``{``/``[`` start in
    # **left-to-right order** and try to parse from there. The first balanced
    # candidate that parses wins. This beats the old greedy ``\{[\s\S]*\}``
    # regex which captured from the first prose-brace to the last JSON-brace
    # and choked on the noise in between (e.g. 8 KB Kimi thinking trace with
    # the actual JSON at the very end).
    pos = 0
    while pos < len(raw):
        # Find the next opener of either flavor.
        next_obj = raw.find('{', pos)
        next_arr = raw.find('[', pos)
        if next_obj < 0 and next_arr < 0:
            break
        if next_obj < 0:
            start, opener, closer = next_arr, '[', ']'
        elif next_arr < 0:
            start, opener, closer = next_obj, '{', '}'
        else:
            if next_obj < next_arr:
                start, opener, closer = next_obj, '{', '}'
            else:
                start, opener, closer = next_arr, '[', ']'

        candidate = _extract_balanced_json(raw, start, opener, closer)
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    pass
        pos = start + 1

    # Last resort: truncated JSON repair. Walks from the first ``{``/``[``
    # and best-effort closes any open brackets to recover.
    json_start = -1
    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            json_start = i
            break

    if json_start >= 0:
        json_str = raw[json_start:]
        result = repair_truncated_json(json_str)
        if result is not None:
            logger.info("json_repair_success", context=context)
            return result

    logger.warning("json_parse_failed", context=context, raw_length=len(raw), raw_preview=raw[:200])
    return {}


def _extract_balanced_json(raw: str, start: int, opener: str, closer: str) -> Optional[str]:
    """Walk ``raw`` from index ``start`` (an opener char) and return the
    substring through the matching closer, respecting string literals + escapes.

    Returns None if the brackets never balance (e.g. truncated response).
    """
    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return None


def repair_truncated_json(json_str: str) -> Any:
    """Attempt to repair truncated JSON by closing open brackets/braces."""
    in_string = False
    escape_next = False
    stack: List[str] = []

    for i, ch in enumerate(json_str):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}':
            if stack and stack[-1] == '{':
                stack.pop()
        elif ch == ']':
            if stack and stack[-1] == '[':
                stack.pop()

    if not stack:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    trimmed = json_str.rstrip()
    if in_string:
        trimmed = trimmed + '"'

    trimmed = trimmed.rstrip(',').rstrip()
    closers = ""
    for bracket in reversed(stack):
        closers += '}' if bracket == '{' else ']'

    repair_attempt = trimmed + closers
    try:
        return json.loads(repair_attempt)
    except json.JSONDecodeError:
        pass
    return None


# ---------------------------------------------------------------------------
# Hook diversity
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-angle hook examples and tone instructions
# ---------------------------------------------------------------------------

ANGLE_HOOK_EXAMPLES: Dict[str, List[str]] = {
    "hidden_truths": [
        "Wolverine's skeleton wasn't always adamantium. The original was worse.",
        "Thanos snapped because of a lie Gamora told him in 2014.",
        "The real reason Dumbledore ignored Harry for a year.",
    ],
    "dark_facts": [
        "Spider-Man once let someone die on purpose. Here's the panel.",
        "Walter White's body count is 201. Most weren't on screen.",
        "The Joker origin DC tried to erase from existence.",
    ],
    "origin_story": [
        "Before the suit, Tony Stark built weapons that killed thousands.",
        "Naruto failed the academy exam 3 times. The third time changed everything.",
        "Batman's first year had nothing to do with justice.",
    ],
    "power_secrets": [
        "Superman has one power nobody talks about. It's not heat vision.",
        "Goku's weakest form is stronger than 99% of the multiverse.",
        "Scarlet Witch rewrote reality with three words.",
    ],
    "character_evolution": [
        "Vegeta went from genocidal prince to father of the year. Here's how.",
        "Zuko's redemption arc took 61 episodes and one cup of tea.",
        "Harley Quinn's evolution from sidekick to anti-hero in 5 key moments.",
    ],
    "fan_theories": [
        "This theory about Jar Jar Binks was confirmed by George Lucas.",
        "The Matrix was supposed to use human brains, not batteries.",
        "Fans predicted Endgame's ending 4 years before it happened.",
    ],
    "behind_scenes": [
        "Heath Ledger locked himself in a hotel room for 6 weeks. This is what he wrote.",
        "The Mandalorian's set was an LED wall. Every background was real-time.",
        "Robert Downey Jr. improvised the most iconic line in MCU history.",
    ],
    "controversial_takes": [
        "Thanos was right. The math actually checks out.",
        "Batman is the weakest member of the Justice League. Fight me.",
        "Sakura is more useful than Naruto in 3 out of 5 arcs.",
    ],
    "vs_comparison": [
        "Goku vs Superman: the answer depends on one rule.",
        "Magneto vs Professor X: only one of them was ever right.",
        "Vader vs Maul: the fight George Lucas almost greenlit.",
    ],
    "storyline_recap": [
        "The Clone Saga was 2 years of chaos. Here's the 6-slide version.",
        "Breaking Bad in 6 facts you forgot happened.",
        "One Piece's Marineford arc changed everything. Here's why.",
    ],
    "power_ranking": [
        "The 5 strongest Avengers are not who you think.",
        "Ranking every Spider-Man villain by actual threat level.",
        "One Piece's top 5 most dangerous Devil Fruits, ranked by destructive power.",
    ],
}

ANGLE_TONE_INSTRUCTIONS: Dict[str, str] = {
    "hidden_truths": "Tone: investigative, revelatory. Build each slide as an uncovered secret. Use phrases like 'here is what actually happened' and 'nobody mentions this part'.",
    "dark_facts": "Tone: provocative, unsettling. Lean into the disturbing details. Use short, punchy sentences. Create tension with '...' pauses before reveals.",
    "origin_story": "Tone: dramatic, cinematic. Tell the origin like a movie trailer. Build from humble beginnings to the defining moment. Use vivid imagery.",
    "power_secrets": "Tone: authoritative, analytical. Present powers like a technical breakdown. Use specific numbers, comparisons, and scaling references.",
    "character_evolution": "Tone: reflective, narrative. Frame the arc as a journey. Contrast who they were vs who they became. Highlight the turning point.",
    "fan_theories": "Tone: conspiratorial, exciting. Present evidence like a case being built. Use 'what if' and 'here is the proof' framing.",
    "behind_scenes": "Tone: insider knowledge, documentary-style. Share production details like exclusive behind-the-curtain access.",
    "controversial_takes": "Tone: bold, debate-sparking. State the take as fact, then back it up. End with a challenge to the audience.",
    "vs_comparison": "Tone: competitive, analytical. Frame as a genuine matchup with specific criteria. Build tension toward the verdict.",
    "storyline_recap": "Tone: epic, sweeping. Condense the story into its most dramatic beats. Each slide should feel like a chapter break.",
    "power_ranking": "Tone: definitive, data-driven. Present rankings with clear criteria. Each entry should have a specific justification.",
}


def get_hook_examples_for_angle(angle: str, count: int = 3) -> List[str]:
    """Return hook examples matching the given angle."""
    examples = ANGLE_HOOK_EXAMPLES.get(angle, [])
    if not examples:
        # Fallback: pick from hidden_truths (most versatile)
        examples = ANGLE_HOOK_EXAMPLES.get("hidden_truths", [])
    return examples[:count]


def get_tone_instruction_for_angle(angle: str) -> Optional[str]:
    """Return tone instruction for the given angle."""
    return ANGLE_TONE_INSTRUCTIONS.get(angle)


_BANNED_HOOK_PATTERNS = (
    r"^the hammer lie\b",
    r"^nobody talks about\b",
    r"^what they (don't|do not|never) (tell|told|want) you\b",
    r"^the truth (about|they hide)\b",
    r"^you (probably )?didn'?t know\b",
    r"^7 secrets? (about|they hide)\b",
)


def is_generic_hook(hook: str, character_name: Optional[str]) -> bool:
    """Return True if the hook is a reused template or fails the swap test."""
    if not hook:
        return True
    lowered = hook.strip().lower()
    normalized = re.sub(r'^[^a-z0-9]+', '', lowered)
    normalized = re.sub(r'\s{2,}', ' ', normalized).strip()
    for pat in _BANNED_HOOK_PATTERNS:
        if re.search(pat, lowered) or re.search(pat, normalized):
            return True
    if character_name:
        if character_name.lower() in lowered:
            return False
        first_name = character_name.split()[0].lower() if character_name else ""
        if first_name and first_name in lowered:
            return False
    words = hook.split()
    has_proper_noun = any(
        len(w) > 2 and w[0].isupper() and not w.isupper() for w in words[1:]
    )
    return not has_proper_noun


def rewrite_generic_hook(hook: str, character_name: str, result: dict) -> str:
    """Rewrite a banned/generic hook into something character-specific."""
    cleaned = hook.strip()
    for pat in _BANNED_HOOK_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip(" :.,-")
    if cleaned and len(cleaned) > 12:
        return f"{character_name}: {cleaned[0].upper() + cleaned[1:]}".rstrip(".")

    for slide in result.get("slides", [])[1:]:
        text = (slide.get("text") or "").strip()
        text = re.sub(r"^\d+\.\s*", "", text)
        if text and not is_generic_hook(text, character_name) and len(text) < 140:
            return text

    return f"{character_name}: the detail everyone misses."


def sanitize_carousel(result: dict, character_name: Optional[str] = None) -> dict:
    """Sanitize all text fields in a carousel result and rewrite generic hooks."""
    if result.get("title"):
        result["title"] = sanitize_text(result["title"])
    if result.get("hook_text"):
        result["hook_text"] = sanitize_text(result["hook_text"], preserve_emphasis=True)
    if result.get("caption"):
        result["caption"] = sanitize_text(result["caption"])
    for slide in result.get("slides", []):
        if slide.get("text"):
            slide["text"] = sanitize_text(slide["text"], preserve_emphasis=True)

    hook = result.get("hook_text") or ""
    if character_name and is_generic_hook(hook, character_name):
        rewritten = rewrite_generic_hook(hook, character_name, result)
        if rewritten and rewritten != hook:
            logger.info(
                "hook_rewritten_generic",
                character=character_name,
                old_hook=hook[:80],
                new_hook=rewritten[:80],
            )
            result["hook_text"] = rewritten
            slides = result.get("slides", [])
            if slides and is_generic_hook(slides[0].get("text", ""), character_name):
                slides[0]["text"] = rewritten

    # Slide 1 has NO body text: the hook already fills slide 1's headline
    # slot. LLMs routinely ignore the "no text" prompt directive and either
    # (a) echo the hook verbatim or (b) paraphrase it — both render as visual
    # duplication on the published slide. Always strip slides[0].text server-
    # side. If someone wants a separate slide-1 body later, they can add it
    # via the editor; the generator will never create one.
    slides = result.get("slides") or []
    if slides:
        first = slides[0]
        first_text = (first.get("text") or "").strip()
        if first_text:
            overlap = 0.0
            if hook:
                try:
                    from app.services.carousel_audit_service import _trigram_overlap
                    overlap = _trigram_overlap(first_text, hook)
                except Exception:  # noqa: BLE001
                    overlap = 1.0 if first_text.lower() == hook.lower() else 0.0
            logger.info(
                "slide_1_text_dropped",
                character=character_name,
                overlap=round(overlap, 2),
                text=first_text[:80],
            )
            first["text"] = ""
    return result


# ---------------------------------------------------------------------------
# ORM to Pydantic converters
# ---------------------------------------------------------------------------

def character_to_pydantic(row: CharacterModel, carousels_created: int = 0) -> Character:
    return Character(
        id=row.id,
        name=row.name,
        universe=row.universe or "other",
        franchise=row.franchise,
        real_name=row.real_name,
        description=row.description,
        image_url=row.image_url,
        image_urls=row.image_urls or [],
        research_data=row.research_data or {},
        research_status=row.research_status or "pending",
        fact_bank=row.fact_bank or [],
        tags=row.tags or [],
        posts_created=row.posts_created or 0,
        carousels_created=carousels_created,
        total_views=row.total_views or 0,
        total_likes=row.total_likes or 0,
        avg_engagement=row.avg_engagement or 0.0,
        status=row.status or "active",
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_researched=row.last_researched,
        research_sources=row.research_sources or [],
        relationship_map=row.relationship_map or {},
        research_depth_score=row.research_depth_score or 0.0,
        content_themes=row.content_themes or [],
        blocked_image_urls=row.blocked_image_urls or [],
        content_ideas=row.content_ideas or [],
    )


def carousel_to_pydantic(row: CharacterCarouselModel, character_name: Optional[str] = None) -> CharacterCarousel:
    slides = row.slides or []
    for slide in slides:
        if slide.get("text"):
            slide["text"] = sanitize_text(slide["text"], preserve_emphasis=True)

    raw_hook = sanitize_text(row.hook_text, preserve_emphasis=True) if row.hook_text else row.hook_text
    if raw_hook and character_name and is_generic_hook(raw_hook, character_name):
        rewritten = rewrite_generic_hook(raw_hook, character_name, {"slides": slides})
        if rewritten and rewritten != raw_hook:
            raw_hook = rewritten

    return CharacterCarousel(
        id=row.id,
        character_id=row.character_id,
        character_name=character_name,
        content_type=getattr(row, "content_type", None) or "character",
        media_title_id=getattr(row, "media_title_id", None),
        media_title_name=None,  # populated by caller when content_type == "media"
        angle=row.angle,
        title=sanitize_text(row.title) if row.title else row.title,
        hook_text=raw_hook,
        slides=slides,
        caption=sanitize_text(row.caption) if row.caption else row.caption,
        hashtags=row.hashtags or [],
        music_mood=row.music_mood,
        ai_review=row.ai_review,
        ai_review_score=(row.ai_review or {}).get("overall_score"),
        human_notes=row.human_notes,
        status=row.status or "draft",
        content_queue_id=row.content_queue_id,
        publish_url=row.publish_url,
        views=row.views,
        likes=row.likes,
        comments=row.comments,
        shares=row.shares,
        saves=row.saves,
        engagement_rate=row.engagement_rate,
        created_at=row.created_at,
        published_at=row.published_at,
        story_template=row.story_template,
        series_id=row.series_id,
        series_part=row.series_part,
        multi_character_ids=row.multi_character_ids or [],
        music_track=row.music_track,
        text_overlay_specs=row.text_overlay_specs or [],
        brain_context_used=row.brain_context_used,
        generation_metadata=row.generation_metadata or {},
        hook_style=getattr(row, "hook_style", None),
        content_format=getattr(row, "content_format", None),
        publish_status=row.publish_status,
        publish_platform=row.publish_platform,
        download_urls=row.download_urls,
        watermark_applied=row.watermark_applied if row.watermark_applied is not None else False,
        final_review=row.final_review,
        final_review_score=row.final_review_score,
        final_review_model=row.final_review_model,
        auto_approved=getattr(row, "auto_approved", None),
        auto_approved_at=getattr(row, "auto_approved_at", None),
        auto_approve_reason=getattr(row, "auto_approve_reason", None),
        current_version_id=getattr(row, "current_version_id", None),
    )


def image_to_pydantic(row: CharacterImageModel) -> CharacterImage:
    return CharacterImage(
        id=row.id,
        character_id=row.character_id,
        url=row.url,
        source=row.source or "manual",
        query_used=row.query_used,
        width=row.width,
        height=row.height,
        is_valid=row.is_valid if row.is_valid is not None else True,
        is_primary=row.is_primary or False,
        usage_count=row.usage_count or 0,
        quality_score=getattr(row, "quality_score", None) or 0.0,
        content_type=getattr(row, "content_type", None),
        file_size=getattr(row, "file_size", None),
        is_approved=getattr(row, "is_approved", None),
        feedback_reason=getattr(row, "feedback_reason", None),
        validated_at=getattr(row, "validated_at", None),
        created_at=row.created_at,
    )


def media_title_to_pydantic(row: MediaTitleModel, character_count: int = 0) -> MediaTitle:
    return MediaTitle(
        id=row.id,
        media_type=row.media_type,
        title=row.title,
        year=row.year,
        end_year=row.end_year,
        genre=row.genre or [],
        franchise=row.franchise,
        universe=row.universe or "other",
        poster_url=row.poster_url,
        backdrop_url=row.backdrop_url,
        synopsis=row.synopsis,
        tagline=row.tagline,
        season_count=row.season_count,
        episode_count=row.episode_count,
        network=row.network,
        show_status=row.show_status,
        runtime_minutes=row.runtime_minutes,
        budget_usd=row.budget_usd,
        box_office_usd=row.box_office_usd,
        mpaa_rating=row.mpaa_rating,
        research_data=row.research_data or {},
        research_status=row.research_status or "pending",
        fact_bank=row.fact_bank or [],
        research_sources=row.research_sources or [],
        research_depth_score=row.research_depth_score or 0.0,
        content_themes=row.content_themes or [],
        tmdb_id=row.tmdb_id,
        imdb_id=row.imdb_id,
        carousels_created=row.carousels_created or 0,
        total_views=row.total_views or 0,
        total_likes=row.total_likes or 0,
        avg_engagement=row.avg_engagement or 0.0,
        status=row.status or "active",
        tags=row.tags or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_researched=row.last_researched,
        character_count=character_count,
    )


def media_image_to_pydantic(row: MediaImageModel) -> MediaImage:
    return MediaImage(
        id=row.id,
        media_title_id=row.media_title_id,
        url=row.url,
        source=row.source or "manual",
        query_used=row.query_used,
        width=row.width,
        height=row.height,
        is_valid=row.is_valid if row.is_valid is not None else True,
        is_primary=row.is_primary or False,
        usage_count=row.usage_count or 0,
        quality_score=getattr(row, "quality_score", None) or 0.0,
        content_type=getattr(row, "content_type", None),
        file_size=getattr(row, "file_size", None),
        is_approved=getattr(row, "is_approved", None),
        feedback_reason=getattr(row, "feedback_reason", None),
        validated_at=getattr(row, "validated_at", None),
        created_at=row.created_at,
    )


def version_to_pydantic(row: CharacterCarouselVersionModel) -> CarouselVersion:
    return CarouselVersion(
        id=row.id,
        carousel_id=row.carousel_id,
        version_number=row.version_number,
        parent_version_id=row.parent_version_id,
        title=row.title,
        hook_text=row.hook_text,
        slides=row.slides or [],
        caption=row.caption,
        hashtags=row.hashtags or [],
        human_notes=row.human_notes,
        music_track=row.music_track,
        text_overlay_specs=row.text_overlay_specs or [],
        source=row.source,
        source_metadata=row.source_metadata or {},
        created_by=row.created_by,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Variant selection (hook_style, story_template) — Thompson Sampling
# ---------------------------------------------------------------------------

def pick_winning_variant(
    stats: List[Dict[str, Any]],
    hook_styles: List[str],
    story_templates: List[str],
    seed: Optional[int] = None,
    min_samples: int = 5,
) -> Dict[str, Any]:
    """Pick a (hook_style, story_template) pair to try next.

    `stats` is a list of dicts with keys: hook_style, story_template, uses, avg_score.
    Scores are on a 0-100 scale (Stage 2 final_review_score) or 0-10 (ai_review).
    We Thompson-sample each pair as a Beta distribution over a Bernoulli success
    (score / scale). Pairs with < min_samples are filled in via deterministic
    rotation so cold-start still covers the space.

    Returns: {hook_style, story_template, method: "thompson"|"rotation", sampled_score?}
    """
    import random as _random

    rng = _random.Random(seed)
    # Build a fast lookup keyed by (hook_style, story_template)
    stats_by_pair: Dict[tuple, Dict[str, Any]] = {}
    for row in stats or []:
        hs = row.get("hook_style")
        st = row.get("story_template")
        if not hs or not st:
            continue
        stats_by_pair[(hs, st)] = row

    all_pairs = [(hs, st) for hs in hook_styles for st in story_templates]
    under_sampled = [
        p for p in all_pairs
        if int((stats_by_pair.get(p) or {}).get("uses", 0) or 0) < min_samples
    ]

    # Cold-start: rotate through pairs that haven't hit min_samples
    if under_sampled:
        choice = under_sampled[(seed or 0) % len(under_sampled)]
        return {
            "hook_style": choice[0],
            "story_template": choice[1],
            "method": "rotation",
        }

    # Thompson Sampling: for each pair, sample from Beta(score_sum+1, miss_sum+1)
    best_pair = None
    best_sample = -1.0
    for pair in all_pairs:
        row = stats_by_pair.get(pair) or {}
        uses = int(row.get("uses", 0) or 0)
        avg = float(row.get("avg_score", 0) or 0)
        # Normalize to 0..1. Stage 2 scores ~0-100; if they look 0-10 scale up.
        scale = 100.0 if avg > 10 or uses == 0 else 10.0
        successes = max(0.0, (avg / scale) * uses)
        failures = max(0.0, uses - successes)
        sample = rng.betavariate(successes + 1.0, failures + 1.0)
        if sample > best_sample:
            best_sample = sample
            best_pair = pair

    hs, st = best_pair or (hook_styles[0], story_templates[0])
    return {
        "hook_style": hs,
        "story_template": st,
        "method": "thompson",
        "sampled_score": round(best_sample, 4),
    }
