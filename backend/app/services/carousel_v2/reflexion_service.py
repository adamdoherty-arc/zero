"""Reflexion loop — converts judge feedback into verbal reinforcement that
the next Designer pass injects.

Three modules per carosel.txt §4: Actor (Designer), Evaluator (judge panel),
Self-Reflector (this module).

Reflections cap at the last 5 entries with periodic compression. Reflection
text is sanitized against prompt injection (HTML strip, length cap,
URL strip) before being concatenated to the Actor's prompt at trial N+1.
"""

from __future__ import annotations

import re

import structlog

from app.models.carousel import CarouselRubric, JudgeAxisScore, RubricAxis

logger = structlog.get_logger(__name__)


_HTML_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
MAX_REFLECTION_LENGTH = 800
MAX_REFLECTIONS = 5


def _sanitize(text: str) -> str:
    if not text:
        return ""
    text = _HTML_RE.sub(" ", text)
    text = _URL_RE.sub("[url]", text)
    return text.strip()[:MAX_REFLECTION_LENGTH]


def make_reflection(rubric: CarouselRubric, *, threshold: float = 6.5) -> str:
    """Generate a coachable reflection from low-scoring axes.

    Picks the 3 lowest axes and writes a short, declarative correction the
    Designer can act on next turn. No URLs, no HTML, length-capped.
    """
    if not rubric.per_axis_per_judge:
        return ""

    by_axis = sorted(rubric.aggregated.items(), key=lambda kv: kv[1])
    weak = [(axis, score) for axis, score in by_axis if score < threshold][:3]
    if not weak:
        return ""

    parts = []
    for axis, score in weak:
        rationales = [
            j.rationale or ""
            for j in rubric.per_axis_per_judge
            if j.axis == axis and j.rationale
        ]
        rationale = " ".join(rationales)[:280]
        parts.append(f"{axis.value} scored {score:.1f}: {rationale}")
    body = "; ".join(parts)
    return _sanitize(body)


def append_reflection(history: list[str], reflection: str) -> list[str]:
    if not reflection:
        return history
    new = list(history) + [reflection]
    return new[-MAX_REFLECTIONS:]


def render_for_designer(history: list[str]) -> str:
    """Stable serialization used inside the Designer's system prompt at
    trial N+1.
    """
    if not history:
        return ""
    return "Past mistakes to avoid:\n" + "\n".join(f"- {h}" for h in history)
