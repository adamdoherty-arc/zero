"""Adversarial Skeptic agent (carosel.txt §3 'Adversarial Skeptic agent').

Different model family from the Designer to avoid shared blind spots —
Designer = local Qwen3 via vLLM, Skeptic = Kimi K2.6 thinking mode.

For each atomic claim returns ``SkepticReport`` with KEEP / REWRITE / KILL
verdict and a ``trap_category`` from a fixed enum (actor_swap, comic_vs_screen,
fan_theory, retcon, made_up_easter_egg, ...).
"""

from __future__ import annotations

from typing import Iterable

import structlog

from app.models.carousel import (
    AtomicFact,
    SkepticReport,
    SkepticVerdict,
    TrapCategory,
)

logger = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are a hostile, pedantic continuity expert reviewing trivia carousels.

For each CLAIM you receive, decide:
- supporting_quote: a direct quote from the EVIDENCE that backs the claim, or null
- trap_category: one of (actor_swap | movie_misattribution | comic_vs_screen |
  fan_theory | retcon | made_up_easter_egg) when applicable, else null
- verdict: KEEP (claim is solid), REWRITE (claim has merit but is imprecise),
  KILL (claim is wrong, unverifiable, or a known fan-fiction trap)
- rewrite_suggestion: a tightened restatement when verdict=REWRITE, else null

Bias toward KILL when uncertain. Comments will be brutal.
Return JSON: a list of objects with keys (claim, supporting_quote, trap_category, verdict, rewrite_suggestion).
"""


async def review(
    claims: list[str],
    *,
    evidence: list[AtomicFact],
    model: str = "kimi/kimi-k2.6",
) -> list[SkepticReport]:
    if not claims:
        return []

    bullets = "\n".join(
        f"- ({f.trust_tier}) {f.subject} {f.predicate} {f.object} ({f.source.url})"
        + (f": {f.source.quote[:240]}" if f.source.quote else "")
        for f in evidence
    )
    claim_block = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
    prompt = f"EVIDENCE:\n{bullets or '(none)'}\n\nCLAIMS:\n{claim_block}"

    try:
        from app.infrastructure.unified_llm_client import UnifiedLLMClient
        result = await UnifiedLLMClient().structured_chat(
            prompt,
            system=SYSTEM_PROMPT,
            output_schema=[
                {
                    "claim": "string",
                    "supporting_quote": "string|null",
                    "trap_category": "actor_swap|movie_misattribution|comic_vs_screen|fan_theory|retcon|made_up_easter_egg|null",
                    "verdict": "KEEP|REWRITE|KILL",
                    "rewrite_suggestion": "string|null",
                }
            ],
            task_type="skeptic",
            temperature=0.0,
            max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("skeptic_call_failed", error=str(exc))
        return [
            SkepticReport(claim=c, verdict=SkepticVerdict.KEEP, supporting_quote=None)
            for c in claims
        ]

    rows = result if isinstance(result, list) else result.get("verdicts", []) if isinstance(result, dict) else []
    out: list[SkepticReport] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            out.append(_to_report(row))
        except Exception as exc:  # noqa: BLE001
            logger.debug("skeptic_row_parse_failed", error=str(exc), row=row)
    # Pad missing rows with KEEP fallbacks to keep slide-count alignment.
    while len(out) < len(claims):
        out.append(SkepticReport(claim=claims[len(out)], verdict=SkepticVerdict.KEEP))
    return out


def _to_report(row: dict) -> SkepticReport:
    verdict_raw = (row.get("verdict") or "KEEP").upper()
    verdict = {"KEEP": SkepticVerdict.KEEP, "REWRITE": SkepticVerdict.REWRITE, "KILL": SkepticVerdict.KILL}.get(
        verdict_raw, SkepticVerdict.KEEP
    )
    trap_raw = row.get("trap_category")
    trap = None
    if trap_raw and trap_raw != "null":
        try:
            trap = TrapCategory(trap_raw)
        except ValueError:
            trap = None
    return SkepticReport(
        claim=row.get("claim") or "",
        supporting_quote=row.get("supporting_quote"),
        trap_category=trap,
        verdict=verdict,
        rewrite_suggestion=row.get("rewrite_suggestion"),
    )


def apply_verdicts(slides: list[dict], reports: list[SkepticReport]) -> tuple[list[dict], dict[str, int]]:
    """Apply KEEP / REWRITE / KILL verdicts to slide texts.

    Matches each slide to a verdict by:

      1. exact text match (lowercased) — same string the activity passed to the LLM
      2. fallback: any verdict whose claim is a substring of the slide (or vice-versa)

    The fallback handles multi-conjunction slides where ``decompose_to_claims``
    split the sentence into sub-claims and the LLM returned a verdict keyed on
    the sub-claim rather than the full slide text.

    Returns ``(updated_slides, counts)`` where counts tally each verdict.
    KILLs drop the slide; REWRITEs replace the text; KEEPs pass through.
    """
    if not reports:
        return slides, {"keep": 0, "rewrite": 0, "kill": 0}

    by_claim = {r.claim.strip().lower(): r for r in reports if r.claim}

    def _match(text_lc: str) -> SkepticReport | None:
        if text_lc in by_claim:
            return by_claim[text_lc]
        for claim_lc, rep in by_claim.items():
            if claim_lc and (claim_lc in text_lc or text_lc in claim_lc):
                return rep
        return None

    counts = {"keep": 0, "rewrite": 0, "kill": 0}
    out: list[dict] = []
    for slide in slides:
        text = (slide.get("text") or "").strip().lower()
        report = _match(text)
        if report is None:
            out.append(slide)
            continue
        if report.verdict == SkepticVerdict.KILL:
            counts["kill"] += 1
            continue
        if report.verdict == SkepticVerdict.REWRITE and report.rewrite_suggestion:
            counts["rewrite"] += 1
            new_slide = dict(slide)
            new_slide["text"] = report.rewrite_suggestion
            out.append(new_slide)
            continue
        counts["keep"] += 1
        out.append(slide)
    return out, counts
