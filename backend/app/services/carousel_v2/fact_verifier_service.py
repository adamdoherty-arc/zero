"""Fact verifier — atomic-claim verification + cross-source rule + citation
post-processor.

Phase 3 implements an LLM-based NLI verifier (``Kimi K2.6 / minimax`` via
``unified_llm_client.structured_chat``). Phase 6 can swap in a local
``cross-encoder/nli-deberta-v3-base`` when GPU lands without changing the
public API of this module.

Public surface::

    extract_cited_ids(text)            -> list[str]
    strip_uncited_sentences(text)      -> str
    decompose_to_claims(text, ...)     -> list[str]
    verify_claim(claim, evidence)      -> dict  # {supported: bool, score: float, span: str}
    verify_carousel(slides, facts)     -> dict  # composite report
"""

from __future__ import annotations

import re
from typing import Iterable

import structlog

from app.models.carousel import AtomicFact

logger = structlog.get_logger(__name__)


_CITE_RE = re.compile(r"\[fact_id:([A-Za-z0-9_-]+)\]")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def extract_cited_ids(text: str) -> list[str]:
    return [m.group(1) for m in _CITE_RE.finditer(text or "")]


def strip_uncited_sentences(text: str) -> str:
    if not text:
        return ""
    sents = _SENT_RE.split(text)
    kept = [s for s in sents if _CITE_RE.search(s)]
    return " ".join(kept)


def decompose_to_claims(text: str) -> list[str]:
    """Cheap rule-based decomposition. Each citation-bearing sentence becomes
    one claim; multi-citation sentences split on conjunctions.
    """
    if not text:
        return []
    sentences = [s.strip() for s in _SENT_RE.split(text) if s.strip()]
    out: list[str] = []
    for s in sentences:
        if not _CITE_RE.search(s):
            continue
        parts = re.split(r"\s+(?:and|but|however|though)\s+", s, flags=re.IGNORECASE)
        out.extend(p for p in parts if _CITE_RE.search(p))
    return out


async def verify_claim(claim: str, evidence: list[AtomicFact]) -> dict:
    """Ask the LLM router to entail the claim against the supporting facts.

    Returns ``{supported: bool, score: float in [0,1], span: str}``.
    Failure-soft — returns ``supported=False, score=0.0`` on LLM error.
    """
    if not evidence:
        return {"supported": False, "score": 0.0, "span": ""}

    bullets = "\n".join(
        f"- ({f.trust_tier}) {f.subject} {f.predicate} {f.object} — {f.source.quote or f.source.url}"
        for f in evidence
    )
    prompt = (
        "You are an NLI checker. Decide whether the CLAIM is entailed by the EVIDENCE.\n"
        "Output JSON only: {\"supported\": bool, \"score\": float in [0,1], \"span\": string}.\n"
        "score is your confidence the claim is fully supported by the evidence.\n\n"
        f"EVIDENCE:\n{bullets}\n\nCLAIM:\n{claim.strip()}"
    )
    try:
        from app.infrastructure.unified_llm_client import UnifiedLLMClient
        result = await UnifiedLLMClient().structured_chat(
            prompt,
            output_schema={"supported": True, "score": 0.5, "span": "supporting quote"},
            task_type="fact_verifier",
            temperature=0.0,
            max_tokens=256,
        )
        if isinstance(result, dict):
            return {
                "supported": bool(result.get("supported", False)),
                "score": float(result.get("score", 0.0) or 0.0),
                "span": str(result.get("span", "")),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_claim_failed", error=str(exc))
    return {"supported": False, "score": 0.0, "span": ""}


async def verify_carousel(slides: list[dict], facts_by_id: dict[str, AtomicFact]) -> dict:
    """Verify every claim across all slides. Returns aggregate stats.

    A slide passes when every cited fact resolves and ≥0.7 confidence is
    achieved on every decomposed claim.
    """
    total_claims = 0
    supported_claims = 0
    failed: list[dict] = []

    for slide in slides:
        text = slide.get("text", "")
        for claim in decompose_to_claims(text):
            total_claims += 1
            ids = extract_cited_ids(claim)
            evidence = [facts_by_id[i] for i in ids if i in facts_by_id]
            result = await verify_claim(claim, evidence)
            if result["supported"] and result["score"] >= 0.7:
                supported_claims += 1
            else:
                failed.append({
                    "slide_num": slide.get("slide_num"),
                    "claim": claim,
                    "result": result,
                })
    pass_rate = supported_claims / total_claims if total_claims else 0.0
    return {
        "total_claims": total_claims,
        "supported_claims": supported_claims,
        "pass_rate": pass_rate,
        "failed": failed,
        "passes": pass_rate >= 0.9 and total_claims > 0,
    }
