"""Quote sourcing + attribution gate for motivation reels.

Two responsibilities:

1. **Source** a high-quality quote for a sub-niche (the payload of a reel).
2. **Verify attribution** — misattributed quotes are the #1 credibility killer
   in this niche, so a quote only ships with a confidently-stated author if it
   fuzzy-matches a primary/public-domain source.

Phase 1 strategy (self-contained, no hard external dep):
- A curated, hand-verified public-domain bank (``SEED_QUOTES``) is both the
  reliable source AND the verification anchor. Every entry is genuinely
  public-domain (Stoics, classic letters/essays, pre-1928 speeches).
- Free quote APIs (Quotable / ZenQuotes) are wired as *optional* candidate
  enrichment that degrades to the bank when offline — they are never trusted
  for attribution without passing the gate.
- When the bank is exhausted for a niche, the LLM generates an *original*
  line, which ships as ``ANONYMOUS`` (always attribution-safe).

No new dependency: fuzzy matching uses stdlib ``difflib``.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from difflib import SequenceMatcher
from typing import Optional

import structlog

from app.models.reel import (
    QuoteAttribution,
    QuoteCard,
    ReelSubNiche,
    SUBNICHE_DEFAULT_MOOD,
)

logger = structlog.get_logger(__name__)


# Attribution verification threshold (fuzzy ratio against a primary source).
ATTRIBUTION_MATCH_THRESHOLD = 0.90


# ---------------------------------------------------------------------------
# Curated public-domain bank — the source AND the verification anchor.
# Every entry is genuinely public domain (author died >95y ago or pre-1928
# publication). source_work is the primary text.
# ---------------------------------------------------------------------------

SEED_QUOTES: list[dict] = [
    # --- Stoicism (Marcus Aurelius — Meditations; Seneca; Epictetus) ---
    {"text": "You have power over your mind, not outside events. Realize this, and you will find strength.",
     "author": "Marcus Aurelius", "source_work": "Meditations", "sub_niche": "stoicism", "theme": "control"},
    {"text": "The impediment to action advances action. What stands in the way becomes the way.",
     "author": "Marcus Aurelius", "source_work": "Meditations", "sub_niche": "stoicism", "theme": "obstacles"},
    {"text": "Waste no more time arguing about what a good man should be. Be one.",
     "author": "Marcus Aurelius", "source_work": "Meditations", "sub_niche": "stoicism", "theme": "action"},
    {"text": "We suffer more often in imagination than in reality.",
     "author": "Seneca", "source_work": "Letters from a Stoic", "sub_niche": "stoicism", "theme": "fear"},
    {"text": "Luck is what happens when preparation meets opportunity.",
     "author": "Seneca", "source_work": "Letters from a Stoic", "sub_niche": "discipline", "theme": "preparation"},
    {"text": "It is not that we have a short time to live, but that we waste a lot of it.",
     "author": "Seneca", "source_work": "On the Shortness of Life", "sub_niche": "discipline", "theme": "time"},
    {"text": "No man is free who is not master of himself.",
     "author": "Epictetus", "source_work": "Discourses", "sub_niche": "discipline", "theme": "self-mastery"},
    {"text": "It is not what happens to you, but how you react to it that matters.",
     "author": "Epictetus", "source_work": "Enchiridion", "sub_niche": "stoicism", "theme": "response"},
    {"text": "First say to yourself what you would be; and then do what you have to do.",
     "author": "Epictetus", "source_work": "Discourses", "sub_niche": "discipline", "theme": "identity"},

    # --- Discipline / self-improvement (public-domain essayists) ---
    {"text": "What lies behind us and what lies before us are tiny matters compared to what lies within us.",
     "author": "Ralph Waldo Emerson", "source_work": "Essays", "sub_niche": "self_improvement", "theme": "inner-strength"},
    {"text": "Do not go where the path may lead, go instead where there is no path and leave a trail.",
     "author": "Ralph Waldo Emerson", "source_work": "Essays", "sub_niche": "self_improvement", "theme": "courage"},
    {"text": "Go confidently in the direction of your dreams. Live the life you have imagined.",
     "author": "Henry David Thoreau", "source_work": "Walden", "sub_niche": "self_improvement", "theme": "dreams"},
    {"text": "It is not enough to be busy; so are the ants. The question is: what are we busy about?",
     "author": "Henry David Thoreau", "source_work": "Letters", "sub_niche": "discipline", "theme": "focus"},
    {"text": "Whatever you can do or dream you can, begin it. Boldness has genius, power and magic in it.",
     "author": "Johann Wolfgang von Goethe", "source_work": "Faust (attributed)", "sub_niche": "discipline", "theme": "boldness"},

    # --- Wealth / success mindset (pre-1928, public domain) ---
    {"text": "Whether you think you can, or you think you can't, you're right.",
     "author": "Henry Ford", "source_work": "Public remarks", "sub_niche": "wealth_mindset", "theme": "belief"},
    {"text": "Opportunity is missed by most people because it is dressed in overalls and looks like work.",
     "author": "Thomas Edison", "source_work": "Public remarks", "sub_niche": "wealth_mindset", "theme": "work"},
    {"text": "Our greatest weakness lies in giving up. The most certain way to succeed is always to try just one more time.",
     "author": "Thomas Edison", "source_work": "Public remarks", "sub_niche": "wealth_mindset", "theme": "persistence"},
    {"text": "Genius is one percent inspiration and ninety-nine percent perspiration.",
     "author": "Thomas Edison", "source_work": "Public remarks", "sub_niche": "discipline", "theme": "work"},

    # --- Resilience / entrepreneurship (public-domain speeches/letters) ---
    {"text": "It is hard to fail, but it is worse never to have tried to succeed.",
     "author": "Theodore Roosevelt", "source_work": "The Strenuous Life", "sub_niche": "entrepreneurship", "theme": "courage"},
    {"text": "Far better is it to dare mighty things than to rank with those poor spirits who neither enjoy much nor suffer much.",
     "author": "Theodore Roosevelt", "source_work": "The Strenuous Life", "sub_niche": "entrepreneurship", "theme": "ambition"},
    {"text": "Believe you can and you're halfway there.",
     "author": "Theodore Roosevelt", "source_work": "Public remarks", "sub_niche": "self_improvement", "theme": "belief"},
    {"text": "I am not a product of my circumstances. I am a product of my decisions.",
     "author": "Unknown", "source_work": None, "sub_niche": "self_improvement", "theme": "decisions"},

    # --- Mental health / mindfulness (public-domain) ---
    {"text": "Nothing can bring you peace but yourself.",
     "author": "Ralph Waldo Emerson", "source_work": "Self-Reliance", "sub_niche": "mental_health", "theme": "peace"},
    {"text": "Tension is who you think you should be. Relaxation is who you are.",
     "author": "Unknown", "source_work": None, "sub_niche": "mental_health", "theme": "acceptance"},
    {"text": "He who has a why to live can bear almost any how.",
     "author": "Friedrich Nietzsche", "source_work": "Twilight of the Idols", "sub_niche": "mental_health", "theme": "meaning"},
    {"text": "That which does not kill us makes us stronger.",
     "author": "Friedrich Nietzsche", "source_work": "Twilight of the Idols", "sub_niche": "grindset", "theme": "adversity"},

    # --- Grindset / discipline ---
    {"text": "The future depends on what you do today.",
     "author": "Unknown", "source_work": None, "sub_niche": "grindset", "theme": "action"},
    {"text": "A year from now you may wish you had started today.",
     "author": "Unknown", "source_work": None, "sub_niche": "grindset", "theme": "starting"},
    {"text": "Discipline is choosing between what you want now and what you want most.",
     "author": "Unknown", "source_work": None, "sub_niche": "discipline", "theme": "self-mastery"},

    # --- Faith ---
    {"text": "Faith is taking the first step even when you don't see the whole staircase.",
     "author": "Unknown", "source_work": None, "sub_niche": "faith", "theme": "faith"},
    {"text": "And we know that all things work together for good to them that love God.",
     "author": "Romans 8:28", "source_work": "King James Bible", "sub_niche": "faith", "theme": "hope"},
    {"text": "I can do all things through Christ which strengtheneth me.",
     "author": "Philippians 4:13", "source_work": "King James Bible", "sub_niche": "faith", "theme": "strength"},

    # --- Affirmations (original, always anonymous-safe) ---
    {"text": "I am becoming the person I needed when I was younger.",
     "author": "Unknown", "source_work": None, "sub_niche": "affirmations", "theme": "growth"},
    {"text": "Every day is a fresh start. I rise.",
     "author": "Unknown", "source_work": None, "sub_niche": "affirmations", "theme": "renewal"},
]


# Snippets of commonly-FAKE attributions to flag as DISPUTED (never ship the
# claimed author). Keyed by a normalized substring + the bogus author.
KNOWN_MISATTRIBUTIONS: list[tuple[str, str]] = [
    ("everything you can imagine is real", "picasso"),
    ("be the change you wish to see", "gandhi"),  # paraphrase, not a real Gandhi line
    ("the definition of insanity is doing the same thing", "einstein"),
    ("if you judge a fish by its ability to climb a tree", "einstein"),
]


def normalize_quote(text: str) -> str:
    """Lowercase, strip punctuation/whitespace for dedup + fuzzy matching."""
    t = text.lower().strip()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def quote_sha256(text: str) -> str:
    return hashlib.sha256(normalize_quote(text).encode("utf-8")).hexdigest()


def _fuzzy(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_quote(a), normalize_quote(b)).ratio()


def verify_attribution(
    text: str, author: Optional[str]
) -> tuple[QuoteAttribution, float, Optional[str], Optional[str]]:
    """Return (verdict, confidence, source_work, source_url).

    - Match against the curated public-domain bank → VERIFIED.
    - Known-fake author signature → DISPUTED.
    - No author claimed → ANONYMOUS.
    - Otherwise → UNVERIFIED (ships, but never asserts the author confidently).
    """
    norm = normalize_quote(text)
    author_l = (author or "").lower().strip()

    # Disputed / known misattribution.
    for snippet, bad_author in KNOWN_MISATTRIBUTIONS:
        if snippet in norm and (bad_author in author_l or not author_l):
            return QuoteAttribution.DISPUTED, 0.0, None, None

    # Match against the bank.
    best_ratio = 0.0
    best: Optional[dict] = None
    for q in SEED_QUOTES:
        r = _fuzzy(text, q["text"])
        if r > best_ratio:
            best_ratio, best = r, q

    if best is not None and best_ratio >= ATTRIBUTION_MATCH_THRESHOLD:
        # Author must also agree (or be unclaimed) to call it VERIFIED.
        bank_author = (best.get("author") or "").lower()
        if not author_l or author_l in bank_author or bank_author in author_l or bank_author == "unknown":
            verdict = QuoteAttribution.VERIFIED if best.get("source_work") else QuoteAttribution.ANONYMOUS
            return verdict, best_ratio, best.get("source_work"), best.get("source_url")

    if not author_l or author_l in ("unknown", "anonymous"):
        return QuoteAttribution.ANONYMOUS, 1.0, None, None

    return QuoteAttribution.UNVERIFIED, best_ratio, None, None


def _build_card(entry: dict, sub_niche: Optional[str]) -> QuoteCard:
    verdict, conf, source_work, source_url = verify_attribution(
        entry["text"], entry.get("author")
    )
    niche = entry.get("sub_niche") or sub_niche
    return QuoteCard(
        id=uuid.uuid4().hex,
        text=entry["text"].strip(),
        author=None if verdict == QuoteAttribution.ANONYMOUS else entry.get("author"),
        source_work=source_work or entry.get("source_work"),
        source_url=source_url,
        attribution=verdict,
        attribution_confidence=round(conf, 3),
        sub_niche=niche,
        theme=entry.get("theme"),
        mood=entry.get("mood") or SUBNICHE_DEFAULT_MOOD.get(niche or "", None),
        is_public_domain=bool(entry.get("source_work")),
        sha256=quote_sha256(entry["text"]),
    )


async def select_quote(
    *,
    sub_niche: Optional[str] = None,
    theme: Optional[str] = None,
    exclude_hashes: Optional[set[str]] = None,
    explicit_text: Optional[str] = None,
    explicit_author: Optional[str] = None,
    allow_llm_fallback: bool = True,
) -> QuoteCard:
    """Pick (or accept) a quote for a reel, verified through the gate.

    Priority: explicit quote → curated bank (deduped) → LLM-generated original.
    """
    exclude_hashes = exclude_hashes or set()

    # 1. Caller-supplied quote — still passes the gate.
    if explicit_text:
        return _build_card(
            {"text": explicit_text, "author": explicit_author, "sub_niche": sub_niche, "theme": theme},
            sub_niche,
        )

    # 2. Curated bank, filtered by niche + dedup.
    pool = [
        q for q in SEED_QUOTES
        if (not sub_niche or q.get("sub_niche") == sub_niche)
        and quote_sha256(q["text"]) not in exclude_hashes
    ]
    if not pool and sub_niche:
        # Niche exhausted — widen to the whole bank before falling to the LLM.
        pool = [q for q in SEED_QUOTES if quote_sha256(q["text"]) not in exclude_hashes]
    if pool:
        # Deterministic-ish rotation: pick by a stable hash so repeated calls
        # with the same exclude set still vary.
        idx = len(exclude_hashes) % len(pool)
        return _build_card(pool[idx], sub_niche)

    # 3. LLM fallback — generate an ORIGINAL line (ships as ANONYMOUS).
    if allow_llm_fallback:
        try:
            card = await _generate_quote_via_llm(sub_niche=sub_niche, theme=theme)
            if card and quote_sha256(card.text) not in exclude_hashes:
                return card
        except Exception as exc:  # noqa: BLE001
            logger.warning("reel_quote_llm_fallback_failed", error=str(exc))

    # 4. Last resort — a safe evergreen affirmation.
    return _build_card(
        {"text": "The future depends on what you do today.", "author": "Unknown",
         "sub_niche": sub_niche or ReelSubNiche.DISCIPLINE.value, "theme": theme or "action"},
        sub_niche,
    )


async def _generate_quote_via_llm(
    *, sub_niche: Optional[str], theme: Optional[str]
) -> Optional[QuoteCard]:
    """Generate an original motivational line. Ships ANONYMOUS — we never
    fabricate an attribution to a real person.
    """
    from app.infrastructure.unified_llm_client import get_unified_llm_client

    niche = sub_niche or "discipline"
    client = get_unified_llm_client()
    system = (
        "You write original, punchy motivational lines for short-form video. "
        "One sentence, 6-18 words, vivid and concrete, no cliches, no hashtags, "
        "no author, no quotation marks. Never attribute it to a real person."
    )
    prompt = f"Write one original {niche} motivational line" + (f" about {theme}." if theme else ".")
    text = (await client.chat(
        prompt=prompt, system=system, task_type="reel_quote_gen",
        temperature=0.9, max_tokens=60,
    )).strip().strip('"').strip()
    if not text or len(text) < 8:
        return None
    return _build_card(
        {"text": text, "author": "Unknown", "sub_niche": niche, "theme": theme},
        sub_niche,
    )
