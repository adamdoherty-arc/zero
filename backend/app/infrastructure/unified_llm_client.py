"""
Unified LLM Client — Central hub for all LLM calls across providers.

Routes requests through the enhanced LLM Router with:
- Automatic provider selection based on task type
- Fallback chains (primary → fallback1 → fallback2 → ...)
- Daily budget enforcement (force Ollama when budget exceeded)
- Circuit breaker per provider
- Usage tracking to PostgreSQL (llm_usage table)
- Metrics recording for dashboards

All existing services continue to work via get_llm_client() which
delegates here transparently.
"""

import asyncio
import json
import re
import time
from functools import lru_cache
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

import structlog

from app.infrastructure.llm_router import get_llm_router
from app.models.llm import parse_provider_model

logger = structlog.get_logger(__name__)

# Global semaphore to prevent LLM resource exhaustion.
# Limits concurrent LLM calls across all providers to prevent:
# - Ollama pool saturation (5 connections)
# - Kimi rate limiting (3 connections)
# - Morning peak cascading failures (9 AM: 4+ jobs fire simultaneously)
_LLM_SEMAPHORE = asyncio.Semaphore(4)


class StructuredOutputError(Exception):
    """Raised when structured output parsing fails after retries."""

    def __init__(self, message: str, raw_response: str = ""):
        super().__init__(message)
        self.raw_response = raw_response


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        start = 1
        end = len(lines)
        if lines[-1].strip() == "```":
            end = -1
        text = "\n".join(lines[start:end]).strip()
    return text


def _try_recover_json(text: str) -> Optional[Union[dict, list]]:
    """Attempt to recover truncated or malformed JSON."""
    text = _strip_code_fences(text)

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to recover truncated arrays: find last complete object and close
    if text.lstrip().startswith("["):
        last_brace = text.rfind("}")
        if last_brace > 0:
            candidate = text[:last_brace + 1].rstrip().rstrip(",") + "]"
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # Try to recover truncated objects
    if text.lstrip().startswith("{"):
        # Count braces to find imbalance
        open_count = text.count("{") - text.count("}")
        if open_count > 0:
            candidate = text + "}" * open_count
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # Try extracting JSON from surrounding text
    for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

    return None


class UnifiedLLMClient:
    """Routes LLM calls to the best provider with fallback and cost tracking."""

    async def chat(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> str:
        """Execute chat with automatic provider routing.

        Model resolution:
        1. Explicit model param (can be 'provider/model' or just 'model')
        2. Task type routing via LLM router
        3. Router default model
        """
        msgs = self._build_messages(prompt, messages, system)

        provider_name, model_name, fallbacks = self._resolve(model, task_type)

        # Budget check — force local (vLLM) if budget exceeded for paid providers
        if provider_name not in ("vllm", "ollama"):
            provider_obj = self._get_provider(provider_name)
            est_tokens = sum(len(m.get("content", "")) for m in msgs) // 4
            est_cost = provider_obj.estimate_cost(est_tokens, est_tokens // 2, model_name)
            if not get_llm_router().check_budget(est_cost):
                logger.warning(
                    "llm_budget_exceeded_forcing_local",
                    provider=provider_name,
                    estimated_cost=est_cost,
                    remaining=get_llm_router().get_remaining_budget(),
                )
                # Fall back to whichever local backend LOCAL_LLM_BACKEND picks.
                import os as _os
                _backend = _os.getenv("LOCAL_LLM_BACKEND", "vllm").strip().lower()
                if _backend == "ollama":
                    provider_name = "ollama"
                    model_name = _os.getenv("OLLAMA_CHAT_MODEL", "qwen3.6:35b-a3b-q8_0")
                else:
                    provider_name = "vllm"
                    model_name = _os.getenv("VLLM_CHAT_MODEL", "qwen3-chat")  # canonical alias resolves via shared-litellm
                fallbacks = []

        return await self._execute_with_fallbacks(
            provider_name, model_name, fallbacks,
            msgs, task_type, temperature, max_tokens,
            json_mode=kwargs.get("json_mode", False),
            thinking_mode=kwargs.get("thinking_mode", False),
        )

    async def chat_stream(
        self,
        prompt: str = "",
        *,
        messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        task_type: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Streaming chat. Yields content chunks."""
        msgs = self._build_messages(prompt, messages, system)
        provider_name, model_name, _ = self._resolve(model, task_type)

        provider = self._get_provider(provider_name)
        async for chunk in provider.chat_stream(
            msgs, model_name, temperature, max_tokens,
        ):
            yield chunk

    async def structured_chat(
        self,
        prompt: str,
        *,
        output_schema: Optional[Union[dict, list]] = None,
        model: Optional[str] = None,
        system: Optional[str] = None,
        task_type: str = "structured_output",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 2,
    ) -> Union[dict, list]:
        """Chat that guarantees valid JSON output with schema enforcement.

        Wraps prompt with structured instructions, strips code fences,
        validates JSON, and retries on failure. Centralizes all the
        JSON parsing/recovery logic duplicated across services.

        Args:
            prompt: The user prompt describing what to extract/generate.
            output_schema: JSON schema or example to guide output shape.
            model: Optional explicit provider/model override.
            system: Optional system prompt.
            task_type: Task type for routing (default: structured_output).
            temperature: Sampling temperature.
            max_tokens: Max response tokens.
            max_retries: Number of retry attempts on invalid JSON.

        Returns:
            Parsed JSON as dict or list.

        Raises:
            StructuredOutputError: After all retries fail.
        """
        schema_str = ""
        if output_schema:
            schema_str = f"\n\nExpected output schema:\n{json.dumps(output_schema, indent=2)}"

        structured_system = (system or "") + (
            "\n\nIMPORTANT: Return ONLY valid JSON. "
            "No markdown code fences, no explanation, no text before or after the JSON."
            f"{schema_str}"
        )

        # For Ollama thinking models, append /no_think to suppress reasoning
        structured_system += " /no_think"

        last_error = None
        raw_response = ""

        for attempt in range(max_retries + 1):
            try:
                if attempt == 0:
                    call_prompt = prompt
                else:
                    call_prompt = (
                        f"{prompt}\n\n"
                        f"RETRY: Your previous response was invalid JSON. "
                        f"Error: {last_error}. "
                        f"Return ONLY valid JSON, nothing else."
                    )

                raw_response = await self.chat(
                    prompt=call_prompt,
                    model=model,
                    system=structured_system,
                    task_type=task_type,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=True,
                )

                result = _try_recover_json(raw_response)
                if result is not None:
                    # Record structured output metrics
                    self._record_structured_metrics(True, attempt, task_type)
                    return result

                last_error = "Response is not valid JSON"
                logger.warning(
                    "structured_chat_invalid_json",
                    attempt=attempt + 1,
                    response_preview=raw_response[:200],
                )

            except StructuredOutputError:
                raise
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "structured_chat_call_failed",
                    attempt=attempt + 1,
                    error=last_error,
                )

        self._record_structured_metrics(False, max_retries + 1, task_type)
        raise StructuredOutputError(
            f"Failed to get valid JSON after {max_retries + 1} attempts. Last error: {last_error}",
            raw_response=raw_response,
        )

    async def plan_then_execute(
        self,
        task: str,
        *,
        context: str = "",
        output_schema: Optional[dict] = None,
        plan_model: Optional[str] = None,
        execute_model: Optional[str] = None,
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        """Kimi plans the task, then Ollama executes each step.

        Three-phase pattern:
        1. PLAN (Kimi): Break task into focused sub-prompts
        2. EXECUTE (Ollama/router): Run each sub-prompt
        3. COMBINE: Return structured results

        Args:
            task: High-level task description.
            context: Domain context data (truncated to 3000 chars).
            output_schema: Expected final output shape.
            plan_model: Optional override for planning model. None routes via task_type="planning".
            execute_model: Optional override for execution model. None routes via task_type.
            max_steps: Max steps in the plan.

        Returns:
            Dict with plan, results, and combined output.
        """
        ctx = context[:3000] + "...(truncated)" if len(context) > 3000 else context

        schema_hint = ""
        if output_schema:
            schema_hint = f"\nThe final combined output should match this schema: {json.dumps(output_schema)}"

        # Phase 1: Plan
        plan_prompt = (
            f"You are a task planner. Break this task into 2-{max_steps} focused steps.\n\n"
            f"Task: {task}\n\n"
            f"Context:\n{ctx}\n\n"
            f"For each step, provide:\n"
            f"- prompt: A self-contained prompt a smaller model can answer\n"
            f"- output_type: 'json' or 'text'\n"
            f"{schema_hint}\n\n"
            f"Return ONLY valid JSON: {{\"steps\": [{{\"prompt\": \"...\", \"output_type\": \"json|text\"}}]}}"
        )

        try:
            plan = await self.structured_chat(
                prompt=plan_prompt,
                task_type="planning",
                temperature=0.2,
                max_tokens=1024,
            )
        except StructuredOutputError:
            # Fallback: single-step execution
            logger.warning("plan_then_execute_planning_failed_single_step")
            result = await self.chat(
                prompt=task, model=plan_model,
                task_type="planning", temperature=0.3, max_tokens=4096,
            )
            return {
                "plan": [{"prompt": task, "output_type": "text"}],
                "results": [result],
                "combined": result,
            }

        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        if not steps:
            result = await self.chat(
                prompt=task, model=plan_model,
                task_type="planning", temperature=0.3, max_tokens=4096,
            )
            return {
                "plan": [{"prompt": task, "output_type": "text"}],
                "results": [result],
                "combined": result,
            }

        # Phase 2: Execute steps with controlled concurrency (max 2 parallel)
        import asyncio as _asyncio
        _step_sem = _asyncio.Semaphore(2)

        async def _run_step(i: int, step: dict):
            async with _step_sem:
                step_prompt = step.get("prompt", "")
                output_type = step.get("output_type", "text")
                logger.info("plan_then_execute_step", step=i + 1, output_type=output_type)
                try:
                    if output_type == "json":
                        return await self.structured_chat(
                            prompt=step_prompt,
                            task_type="extraction",
                            temperature=0.2,
                            max_tokens=2048,
                        )
                    else:
                        return await self.chat(
                            prompt=step_prompt,
                            model=execute_model,
                            task_type="analysis",
                            temperature=0.2,
                            max_tokens=2048,
                        )
                except Exception as e:
                    logger.error("plan_then_execute_step_failed", step=i + 1, error=str(e))
                    return f"[Step {i + 1} failed: {e}]"

        results = await _asyncio.gather(
            *[_run_step(i, step) for i, step in enumerate(steps[:max_steps])]
        )

        # Phase 3: Combine
        results_text = "\n\n".join(
            f"Step {i + 1}: {json.dumps(r) if isinstance(r, (dict, list)) else r}"
            for i, r in enumerate(results)
        )

        combine_prompt = (
            f"Combine these step results into a final answer.\n\n"
            f"Original Task: {task}\n\n"
            f"Step Results:\n{results_text}\n\n"
            f"Provide a clear, well-structured response."
        )

        if output_schema:
            try:
                combined = await self.structured_chat(
                    prompt=combine_prompt,
                    output_schema=output_schema,
                    task_type="structured_output",
                    temperature=0.2,
                    max_tokens=4096,
                )
            except StructuredOutputError:
                combined = await self.chat(
                    prompt=combine_prompt,
                    model=plan_model,
                    task_type="summarization",
                    temperature=0.3,
                    max_tokens=4096,
                )
        else:
            combined = await self.chat(
                prompt=combine_prompt,
                model=plan_model,
                task_type="summarization",
                temperature=0.3,
                max_tokens=4096,
            )

        return {
            "plan": steps,
            "results": results,
            "combined": combined,
        }

    # ------------------------------------------------------------------
    # Structured output metrics
    # ------------------------------------------------------------------

    _structured_stats: Dict[str, Any] = {
        "total_calls": 0,
        "successes": 0,
        "failures": 0,
        "retries": 0,
        "by_task_type": {},
    }

    def _record_structured_metrics(self, success: bool, attempts: int, task_type: str):
        """Record structured output metrics for observability."""
        stats = UnifiedLLMClient._structured_stats
        stats["total_calls"] += 1
        if success:
            stats["successes"] += 1
        else:
            stats["failures"] += 1
        stats["retries"] += max(0, attempts - (1 if success else 0))

        tt = stats["by_task_type"].setdefault(task_type, {"calls": 0, "successes": 0, "failures": 0, "retries": 0})
        tt["calls"] += 1
        if success:
            tt["successes"] += 1
        else:
            tt["failures"] += 1
        tt["retries"] += max(0, attempts - (1 if success else 0))

        # Also record to metrics service
        try:
            from app.services.metrics_service import get_metrics_service
            metrics = get_metrics_service()
            metrics.increment("structured_chat_calls", {"task_type": task_type, "success": str(success)})
            if attempts > 1:
                metrics.increment("structured_chat_retries", {"task_type": task_type})
        except Exception:
            pass

    @classmethod
    def get_structured_stats(cls) -> Dict[str, Any]:
        """Get structured output metrics for the API."""
        stats = cls._structured_stats
        total = stats["total_calls"]
        return {
            "total_calls": total,
            "successes": stats["successes"],
            "failures": stats["failures"],
            "retries": stats["retries"],
            "success_rate": round(stats["successes"] / total * 100, 1) if total > 0 else 0.0,
            "retry_rate": round(stats["retries"] / total * 100, 1) if total > 0 else 0.0,
            "by_task_type": stats["by_task_type"],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        prompt: str,
        messages: Optional[List[Dict[str, str]]],
        system: Optional[str],
    ) -> List[Dict[str, str]]:
        if messages is not None:
            return messages
        result = []
        if system:
            result.append({"role": "system", "content": system})
        if prompt:
            result.append({"role": "user", "content": prompt})
        return result

    def _resolve(
        self,
        model: Optional[str],
        task_type: Optional[str],
    ) -> Tuple[str, str, List[Tuple[str, str]]]:
        """Resolve provider, model, and fallbacks."""
        if model:
            provider, model_name = parse_provider_model(model)
            # Get fallbacks from router if task_type provided
            _, _, fallbacks = get_llm_router().resolve_provider_model(task_type)
            return provider, model_name, fallbacks

        return get_llm_router().resolve_provider_model(task_type)

    def _get_provider(self, name: str):
        from app.infrastructure.llm_providers import get_provider
        return get_provider(name)

    async def _execute_with_fallbacks(
        self,
        provider_name: str,
        model_name: str,
        fallbacks: List[Tuple[str, str]],
        messages: List[Dict[str, str]],
        task_type: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
        thinking_mode: bool = False,
    ) -> str:
        """Try primary provider, then fallback chain on failure.

        Protected by global semaphore to prevent resource exhaustion
        when multiple scheduler jobs fire simultaneously.
        """
        async with _LLM_SEMAPHORE:
            last_error = None

            # Try primary with one retry on transient connection errors. LiteLLM
            # in front of vLLM will sometimes drop the first call during a
            # model swap ("Server disconnected without sending a response"),
            # then succeed on the second. Retrying here avoids falling through
            # to misconfigured fallbacks (e.g. expired MiniMax/Kimi keys).
            for attempt in range(2):
                try:
                    return await self._call_provider(
                        provider_name, model_name, messages,
                        task_type, temperature, max_tokens,
                        json_mode=json_mode,
                        thinking_mode=thinking_mode,
                    )
                except Exception as e:
                    last_error = e
                    err_s = str(e)
                    transient = (
                        "Server disconnected" in err_s
                        or "ReadError" in err_s
                        or "ConnectError" in err_s
                        or "RemoteProtocolError" in err_s
                        or "ReadTimeout" in err_s
                    )
                    logger.warning(
                        "llm_primary_failed",
                        provider=provider_name,
                        model=model_name,
                        attempt=attempt + 1,
                        transient=transient,
                        error=err_s,
                    )
                    if attempt == 0 and transient:
                        await asyncio.sleep(1.0)
                        continue
                    break

            # Try fallbacks (thinking_mode disabled for fallbacks — only Kimi supports it)
            for fb_provider, fb_model in fallbacks:
                try:
                    logger.info("llm_fallback_attempt", provider=fb_provider, model=fb_model)
                    return await self._call_provider(
                        fb_provider, fb_model, messages,
                        task_type, temperature, max_tokens,
                        json_mode=json_mode if fb_provider in ("gemini", "kimi", "vllm") else False,
                    )
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "llm_fallback_failed",
                        provider=fb_provider,
                        model=fb_model,
                        error=str(e),
                    )

            raise Exception(f"All LLM providers failed. Last error: {last_error}")

    async def _call_provider(
        self,
        provider_name: str,
        model_name: str,
        messages: List[Dict[str, str]],
        task_type: Optional[str],
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
        thinking_mode: bool = False,
    ) -> str:
        """Call a specific provider with metrics + cost tracking + Langfuse trace.

        Langfuse tracing (added in carosel.txt blueprint Phase 1) wraps every
        LLM call in a ``generation`` span. The tracer is a no-op when
        ``ZERO_LANGFUSE_PUBLIC_KEY`` is unset, so existing services see no
        behaviour change until keys are added.
        """
        provider = self._get_provider(provider_name)
        t0 = time.monotonic()
        prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        success = True
        error_msg = None
        result = ""

        # Langfuse trace — lazy-imported to keep import-time cost low.
        from app.infrastructure.langfuse_client import get_langfuse_tracer
        tracer = get_langfuse_tracer()

        try:
            chat_kwargs: Dict[str, Any] = {
                "messages": messages,
                "model": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode and provider_name in ("gemini", "kimi", "vllm"):
                chat_kwargs["json_mode"] = True
            if thinking_mode and provider_name == "kimi":
                chat_kwargs["thinking_mode"] = True

            async with tracer.trace_generation(
                name=task_type or "chat",
                model=f"{provider_name}/{model_name}",
                metadata={
                    "provider": provider_name,
                    "task_type": task_type,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "json_mode": json_mode,
                    "thinking_mode": thinking_mode,
                },
                input_messages=messages,
            ) as generation:
                result = await provider.chat(**chat_kwargs)
                try:
                    generation.update(
                        output=result,
                        usage={
                            "input": prompt_tokens,
                            "output": len(result) // 4 if result else 0,
                            "unit": "TOKENS",
                        },
                    )
                except Exception:  # noqa: BLE001 — tracing must never break calls
                    pass
                return result
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            completion_tokens = len(result) // 4 if result else 0
            cost = provider.estimate_cost(prompt_tokens, completion_tokens, model_name)

            # Record spend (global + per-provider)
            if cost > 0:
                try:
                    await get_llm_router().record_spend(cost, provider=provider_name)
                except Exception:
                    pass

            # Record to DB (fire-and-forget)
            try:
                await self._record_usage(
                    provider_name, model_name, task_type,
                    prompt_tokens, completion_tokens, cost,
                    elapsed_ms, success, error_msg,
                )
            except Exception:
                pass

            # Record to metrics service
            try:
                from app.services.metrics_service import get_metrics_service
                metrics = get_metrics_service()
                metrics.record("llm_response_time", elapsed_ms, {"provider": provider_name})
                metrics.increment("llm_requests", {"provider": provider_name, "success": str(success)})
            except Exception:
                pass

    async def _record_usage(
        self,
        provider: str,
        model: str,
        task_type: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        latency_ms: float,
        success: bool,
        error_message: Optional[str],
    ):
        """Persist usage record to PostgreSQL."""
        from app.infrastructure.database import get_session
        from app.db.models import LlmUsageModel

        async with get_session() as session:
            usage = LlmUsageModel(
                provider=provider,
                model=model,
                task_type=task_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                success=success,
                error_message=error_message,
            )
            session.add(usage)


@lru_cache()
def get_unified_llm_client() -> UnifiedLLMClient:
    """Get the singleton unified LLM client."""
    return UnifiedLLMClient()
