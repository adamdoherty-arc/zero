"""
Reflection Service for Zero Brain.

Implements the Analyze -> Critique -> Improve -> Validate loop.
Used by content creation, research, and experiment systems.
"""

from typing import List, Optional, Dict, Any
from functools import lru_cache

import structlog

from app.infrastructure.unified_llm_client import get_unified_llm_client

logger = structlog.get_logger(__name__)

DEFAULT_CRITERIA = [
    "accuracy", "completeness", "actionability", "clarity", "specificity",
]

ANALYSIS_PROMPT = """Evaluate this {content_type} against these criteria: {criteria}
Score each criterion 0-100 and identify specific issues.

Content:
{content}

Return JSON: {{"scores": {{"criterion": score}}, "overall": number, "issues": ["issue1", "issue2"]}}"""

CRITIQUE_PROMPT = """You are a critical reviewer. Find weaknesses in this {content_type}:

{content}

Previous analysis found these issues: {issues}

Provide 2-3 specific, actionable critiques. Be tough but fair. Return JSON:
{{"critiques": ["critique1", "critique2"], "severity": "low|medium|high"}}"""

IMPROVE_PROMPT = """Improve this {content_type} based on these critiques:

Critiques:
{critiques}

Original content:
{content}

Return the IMPROVED content only, no explanation."""

VALIDATE_PROMPT = """Score this improved {content_type} against criteria: {criteria}

Content:
{content}

Return JSON: {{"scores": {{"criterion": score}}, "overall": number, "improved_areas": ["area1"]}}"""


class ReflectionService:
    """Analyze -> Critique -> Improve -> Validate loop."""

    async def reflect(
        self,
        content: str,
        content_type: str = "general",
        criteria: Optional[List[str]] = None,
        max_iterations: int = 3,
        quality_threshold: float = 75.0,
    ) -> Dict[str, Any]:
        """Run reflection loop on content.

        Returns: {final_content, iterations, improvements_made, quality_scores}
        """
        if not content:
            return {"final_content": content, "iterations": 0,
                    "improvements_made": [], "quality_scores": []}

        criteria = criteria or DEFAULT_CRITERIA
        criteria_str = ", ".join(criteria)
        llm = get_unified_llm_client()

        current_content = content
        improvements = []
        scores = []

        for iteration in range(max_iterations):
            try:
                # 1. Analyze
                analysis = await llm.structured_chat(
                    prompt=ANALYSIS_PROMPT.format(
                        content_type=content_type,
                        criteria=criteria_str,
                        content=current_content[:3000],
                    ),
                    task_type="analysis",
                    temperature=0.1,
                )

                overall_score = float(analysis.get("overall", 50))
                issues = analysis.get("issues", [])
                scores.append({"iteration": iteration, "score": overall_score,
                              "scores": analysis.get("scores", {})})

                # Stop if quality threshold met — validate first so the final
                # score is calibrated before we exit the loop.
                if overall_score >= quality_threshold and iteration > 0:
                    logger.info("reflection_threshold_met",
                              iteration=iteration, score=overall_score)
                    try:
                        validation = await llm.structured_chat(
                            prompt=VALIDATE_PROMPT.format(
                                content_type=content_type,
                                criteria=criteria_str,
                                content=current_content[:3000],
                            ),
                            task_type="analysis",
                            temperature=0.1,
                        )
                        final_score = float(validation.get("overall", overall_score))
                        scores.append({"iteration": iteration + 0.5,
                                      "score": final_score, "validation": True})
                    except Exception as _e:
                        # Fix-117 (RFL5): don't swallow silently. A failing
                        # validate leaves no calibrated score appended, so the
                        # reported final_score silently reverts to the pre-validate
                        # analyze score — surface it so a systematic validation
                        # failure is visible instead of masquerading as success.
                        logger.warning("reflection_validation_failed",
                                       iteration=iteration, error=str(_e))
                    break

                # 2. Critique
                critique = await llm.structured_chat(
                    prompt=CRITIQUE_PROMPT.format(
                        content_type=content_type,
                        content=current_content[:3000],
                        issues="; ".join(issues[:5]),
                    ),
                    task_type="analysis",
                    temperature=0.2,
                )

                critiques = critique.get("critiques", [])
                if not critiques:
                    # Fix-119 (RFL-2): empty critiques == "good enough", but the
                    # loop previously broke here WITHOUT validating, so on this
                    # (common) exit the reported final_score reverted to the
                    # pre-validate analyze score — an uncalibrated number
                    # reported as the calibrated final. Validate before breaking,
                    # mirroring the threshold path above.
                    try:
                        validation = await llm.structured_chat(
                            prompt=VALIDATE_PROMPT.format(
                                content_type=content_type,
                                criteria=criteria_str,
                                content=current_content[:3000],
                            ),
                            task_type="analysis",
                            temperature=0.1,
                        )
                        final_score = float(validation.get("overall", overall_score))
                        scores.append({"iteration": iteration + 0.5,
                                      "score": final_score, "validation": True})
                    except Exception as _e:
                        logger.warning("reflection_validation_failed",
                                       iteration=iteration, error=str(_e))
                    break

                # 3. Improve
                improved = await llm.chat(
                    prompt=IMPROVE_PROMPT.format(
                        content_type=content_type,
                        critiques="\n".join(f"- {c}" for c in critiques),
                        content=current_content[:3000],
                    ),
                    task_type="analysis",
                    temperature=0.3,
                    max_tokens=4096,
                )

                # Fix-92: accept any substantive rewrite via a non-emptiness
                # floor. The old `> len(current) * 0.3` gate discarded a
                # correctly-tightened shorter answer, structurally rewarding
                # verbosity over concision.
                if improved and len(improved.strip()) >= 40:
                    current_content = improved.strip()
                    improvements.append({
                        "iteration": iteration,
                        "critiques": critiques,
                        "severity": critique.get("severity", "medium"),
                    })

                # 4. Validate (on last iteration only — threshold path validated above)
                if iteration == max_iterations - 1:
                    # Fix-123 (RFL): guard the final-iteration validate the same
                    # way the threshold (line 106) and empty-critique (line 148)
                    # paths were guarded in Fix-117/119. Without its own
                    # try/except, a validate failure here fell to the outer
                    # `except` and logged the generic "reflection_iteration_failed"
                    # — masking a *validation* failure as a generic one and still
                    # reverting the reported final_score to the pre-validate
                    # analyze score. Surface it specifically, consistent with the
                    # other two exits.
                    try:
                        validation = await llm.structured_chat(
                            prompt=VALIDATE_PROMPT.format(
                                content_type=content_type,
                                criteria=criteria_str,
                                content=current_content[:3000],
                            ),
                            task_type="analysis",
                            temperature=0.1,
                        )
                        final_score = float(validation.get("overall", overall_score))
                        scores.append({"iteration": iteration + 0.5,
                                      "score": final_score, "validation": True})
                    except Exception as _e:
                        logger.warning("reflection_validation_failed",
                                       iteration=iteration, error=str(_e))

            except Exception as e:
                logger.warning("reflection_iteration_failed",
                             iteration=iteration, error=str(e))
                break

        logger.info("reflection_complete",
                    iterations=len(improvements),
                    initial_score=scores[0]["score"] if scores else 0,
                    final_score=scores[-1]["score"] if scores else 0)

        return {
            "final_content": current_content,
            "iterations": len(improvements),
            "improvements_made": improvements,
            "quality_scores": scores,
        }

    async def reflect_on_decisions(
        self,
        decisions: List[Dict[str, Any]],
        domain: str,
    ) -> List[str]:
        """Periodic reflection on recent decisions and their outcomes.

        Returns list of meta-learnings.
        """
        if not decisions:
            return []

        try:
            llm = get_unified_llm_client()

            decisions_text = "\n".join(
                f"- {d.get('action_type', 'unknown')}: strategy='{d.get('strategy', 'unknown')}', "
                f"predicted={d.get('predicted', 'N/A')}, actual={d.get('actual', 'N/A')}"
                for d in decisions[:20]
            )

            result = await llm.structured_chat(
                prompt=(
                    f"Reflect on these {domain} decisions and outcomes:\n\n"
                    f"{decisions_text}\n\n"
                    f"Extract 3-5 meta-learnings. What patterns emerge? "
                    f"What should change going forward?"
                ),
                output_schema=[{"learning": "string", "confidence": "number"}],
                task_type="analysis",
                temperature=0.2,
            )

            # structured_chat may hand back a top-level list OR a dict wrapper
            # (e.g. {"learnings": [...]}); unwrap the dict so meta-learnings
            # aren't silently dropped for the learn loop.
            if isinstance(result, dict):
                result = (
                    result.get("learnings")
                    or result.get("results")
                    or result.get("items")
                    or []
                )
            if isinstance(result, list):
                return [
                    item.get("learning", "")
                    for item in result
                    if isinstance(item, dict) and item.get("learning")
                ]
            return []

        except Exception as e:
            logger.error("decision_reflection_failed", error=str(e))
            return []


@lru_cache()
def get_reflection_service() -> ReflectionService:
    return ReflectionService()
