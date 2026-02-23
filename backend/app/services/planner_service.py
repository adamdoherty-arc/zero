"""
Gemini-powered Planner Service.

Uses Gemini 3.1 Pro as the "brain" to decompose complex tasks into
subtasks, delegates simple subtasks to local Ollama (free), and
synthesizes the final result.

Three-phase pattern:
1. PLAN (Gemini): Break task into steps, tag complexity
2. EXECUTE (mixed): Simple → Ollama, moderate → OpenRouter, complex → Gemini
3. SYNTHESIZE (Gemini): Combine step results into final answer
"""

import json
from typing import Any, Dict, List, Optional

import structlog

from app.infrastructure.unified_llm_client import get_unified_llm_client

logger = structlog.get_logger(__name__)

# Model routing by complexity tier
COMPLEXITY_MODELS = {
    "simple": "ollama/qwen3:8b",
    "moderate": "ollama/qwen3:8b",  # Use Ollama for moderate too (conservative budget)
    "complex": "gemini/gemini-3.1-pro-preview",
}

PLAN_MODEL = "gemini/gemini-3.1-pro-preview"
SYNTHESIS_MODEL = "gemini/gemini-3.1-pro-preview"


class PlannerService:
    """Gemini-powered task decomposition and delegation."""

    async def plan_and_execute(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Three-phase execution: Plan → Execute → Synthesize.

        Args:
            task_description: What the user wants done.
            context: Optional dict of domain data (sprints, emails, etc.).

        Returns:
            Dict with plan, step_results, and final_response.
        """
        context = context or {}
        client = get_unified_llm_client()

        # Phase 1: Planning
        logger.info("planner_phase_1_planning", task=task_description[:100])
        plan = await self._create_plan(client, task_description, context)

        if not plan or not plan.get("steps"):
            # Fallback: single-step execution
            logger.info("planner_single_step_fallback")
            result = await client.chat(
                prompt=task_description,
                model=PLAN_MODEL,
                task_type="planning",
                temperature=0.3,
                max_tokens=2048,
            )
            return {
                "task": task_description,
                "plan": {"steps": [{"description": task_description, "complexity": "complex"}]},
                "step_results": [{"step": 1, "result": result, "model_used": PLAN_MODEL}],
                "final_response": result,
            }

        # Phase 2: Execution
        logger.info("planner_phase_2_execution", step_count=len(plan["steps"]))
        step_results = await self._execute_steps(client, plan["steps"], context)

        # Phase 3: Synthesis
        logger.info("planner_phase_3_synthesis")
        final_response = await self._synthesize(
            client, task_description, step_results,
        )

        return {
            "task": task_description,
            "plan": plan,
            "step_results": step_results,
            "final_response": final_response,
        }

    async def _create_plan(
        self,
        client,
        task_description: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Phase 1: Use Gemini to decompose task into steps."""
        # Truncate context to avoid huge prompts
        context_str = json.dumps(context, default=str)
        if len(context_str) > 3000:
            context_str = context_str[:3000] + "...(truncated)"

        plan_prompt = f"""You are a task planner. Break down this task into 2-5 discrete steps.

Task: {task_description}

Available Context:
{context_str}

For each step, specify:
- description: What to do (be specific)
- complexity: "simple" (quick lookup or formatting) | "moderate" (analysis or summarization) | "complex" (deep reasoning or multi-source synthesis)

Respond ONLY with valid JSON, no markdown:
{{"steps": [{{"description": "...", "complexity": "simple|moderate|complex"}}]}}"""

        try:
            response = await client.chat(
                prompt=plan_prompt,
                model=PLAN_MODEL,
                task_type="planning",
                temperature=0.2,
                max_tokens=1024,
            )
            # Extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                # Strip markdown code fences
                lines = response.split("\n")
                response = "\n".join(
                    l for l in lines if not l.strip().startswith("```")
                )
            return json.loads(response)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("planner_json_parse_failed", error=str(e))
            return {"steps": []}

    async def _execute_steps(
        self,
        client,
        steps: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Phase 2: Execute each step with appropriate model."""
        results = []

        for idx, step in enumerate(steps):
            complexity = step.get("complexity", "simple")
            model = COMPLEXITY_MODELS.get(complexity, "ollama/qwen3:8b")

            logger.info(
                "planner_step_execute",
                step=idx + 1,
                complexity=complexity,
                model=model,
            )

            step_prompt = f"""Execute this task step:

{step['description']}

Context (use what's relevant):
{json.dumps(context, default=str)[:2000]}

Provide a concise, actionable result."""

            try:
                step_result = await client.chat(
                    prompt=step_prompt,
                    model=model,
                    task_type="analysis",
                    temperature=0.2,
                    max_tokens=1024,
                )
            except Exception as e:
                logger.error("planner_step_failed", step=idx + 1, error=str(e))
                step_result = f"[Step failed: {e}]"

            results.append({
                "step": idx + 1,
                "description": step["description"],
                "complexity": complexity,
                "result": step_result,
                "model_used": model,
            })

        return results

    async def _synthesize(
        self,
        client,
        task_description: str,
        step_results: List[Dict[str, Any]],
    ) -> str:
        """Phase 3: Use Gemini to combine step results into final answer."""
        results_text = "\n\n".join(
            f"Step {r['step']} ({r['complexity']}): {r['description']}\nResult: {r['result']}"
            for r in step_results
        )

        synthesis_prompt = f"""Synthesize a final answer to the original task.

Original Task: {task_description}

Step Results:
{results_text}

Provide a clear, well-structured final response that directly addresses the original task.
Be conversational and helpful. Format for Discord (use markdown sparingly)."""

        return await client.chat(
            prompt=synthesis_prompt,
            model=SYNTHESIS_MODEL,
            task_type="summarization",
            temperature=0.3,
            max_tokens=2048,
        )


def get_planner_service() -> PlannerService:
    """Get the planner service instance."""
    return PlannerService()
