"""FreeLLMAPI client — emergency last-resort LLM fallback (Bifrost-Chain-03).

Thin OpenAI-compatible client that talks to the `shared-freellmapi` container
at `http://shared-freellmapi:3001/v1` (or ZERO_FREELLM_BASE_URL / FREELLM_BASE_URL
override). freellmapi internally aggregates the free tiers of ~14 providers
(Google, Groq, Cerebras, SambaNova, NVIDIA NIM, Mistral, OpenRouter, GitHub
Models, Cloudflare, Cohere, Z.ai, Ollama Cloud) behind a priority-ordered
fallback chain with per-key RPM/RPD/TPM/TPD tracking.

Role in Zero's chain (post-2026-05-25, Bifrost-Chain-03):

    1. Kimi via Bifrost (moonshot/kimi-k2.6) — primary cloud
    2. Local Qwen via Bifrost (vllm-local/Qwen3-32B-AWQ) — primary local
    3. THIS CLIENT — emergency cross-provider free-tier fallback chain
    4. Whatever per-task fallback the LlmRouter has configured

Env vars (ZERO_*-prefixed read first, plain FREELLM_* fallback for cross-project
consistency with Legion/ADA):
    ZERO_FREELLM_BASE_URL or FREELLM_BASE_URL    (default http://shared-freellmapi:3001/v1)
    ZERO_FREELLM_BEARER_TOKEN or FREELLM_BEARER_TOKEN
    ZERO_FREELLM_TIMEOUT_SECONDS or FREELLM_TIMEOUT_SECONDS (default 90s)

This client does NOT implement chain logic — that lives entirely upstream.
Our job is:

  1. Make the call with the unified bearer token.
  2. Parse `X-Routed-Via` and `X-Fallback-Attempts` response headers for audit.
  3. Surface meaningful errors so the caller's provider_errors chain can
     record them.

Modelled after Legion's c:\\code\\legion\\backend\\app\\services\\llm_clients\\freellm_client.py
and ADA's c:\\code\\ADA\\backend\\infrastructure\\freellm_client.py.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


def _default_base_url() -> str:
    """Resolve the freellmapi base URL.

    Reads ZERO_FREELLM_BASE_URL first (Zero's ZERO_*-prefix convention),
    falls back to plain FREELLM_BASE_URL (Legion/ADA shared convention),
    then to the docker service name default.
    """
    url = (
        os.getenv("ZERO_FREELLM_BASE_URL")
        or os.getenv("FREELLM_BASE_URL")
        or "http://shared-freellmapi:3001/v1"
    )
    return url.rstrip("/")


def _default_timeout() -> float:
    raw = os.getenv("ZERO_FREELLM_TIMEOUT_SECONDS") or os.getenv("FREELLM_TIMEOUT_SECONDS", "90")
    try:
        return float(raw)
    except ValueError:
        return 90.0


def _bearer_token() -> str:
    return (
        os.getenv("ZERO_FREELLM_BEARER_TOKEN")
        or os.getenv("FREELLM_BEARER_TOKEN")
        or ""
    )


# Set once, per process, the first time freellmapi rejects our bearer token.
# See is_freellm_available() for why presence of a token is not availability.
_AUTH_REJECTED: dict[str, Any] = {"at": None, "status": None, "token_suffix": None}


def note_auth_rejected(status: int, token: str) -> None:
    """Latch the tier OFF after freellmapi rejects our credentials.

    A 401/403 is not transient and not per-request: the token either matches
    freellmapi's unified key or it never will, for the life of this process.
    Without the latch, every single LLM call in Zero spends a full round-trip
    on a tier that is guaranteed to refuse it -- and because the emergency tier
    sits at the END of the chain, that cost is paid precisely when everything
    else has already failed and latency matters most.
    """
    if _AUTH_REJECTED["at"] is not None:
        return
    _AUTH_REJECTED.update(
        {"at": time.time(), "status": status, "token_suffix": (token or "")[-6:]}
    )
    logger.error(
        "freellm_auth_rejected_tier_disabled",
        status=status,
        token_suffix=(token or "")[-6:],
        action=(
            "emergency LLM tier DISABLED for this process. freellmapi rejected "
            "our unified bearer token. Fix: copy the current key from "
            "shared-freellmapi (settings.unified_api_key) into "
            "ZERO_FREELLM_BEARER_TOKEN and restart."
        ),
    )


def freellm_auth_state() -> dict[str, Any]:
    """Expose the latch for health/readiness reporting."""
    return dict(_AUTH_REJECTED)


def is_freellm_available() -> bool:
    """True if freellmapi is usable: a token is set AND has not been rejected.

    The token-presence check alone was a probe that always passed. Measured
    2026-07-31: Zero's ZERO_FREELLM_BEARER_TOKEN still held a key that had been
    rotated out of shared-freellmapi at some point -- Legion, ADA and
    shared-infra/.env all carried the current one, Zero alone was stale -- so
    every completion returned `HTTP 401 Invalid API key` while this function
    cheerfully returned True. The emergency tier had been dead for an unknown
    period and nothing anywhere said so, because "a token is configured" was
    being treated as "the tier works".
    """
    return bool(_bearer_token()) and _AUTH_REJECTED["at"] is None


class FreeLLMAPIClient:
    """OpenAI-compatible client for `shared-freellmapi`."""

    def __init__(
        self,
        base_url: str | None = None,
        bearer_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self.bearer_token = bearer_token or _bearer_token()
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else _default_timeout()
        )
        if not self.bearer_token:
            logger.warning(
                "freellm_bearer_token_empty",
                msg="FREELLM_BEARER_TOKEN is empty — calls will 401. Set it from the shared-freellmapi dashboard Keys page.",
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _extract_routing(headers: httpx.Headers) -> dict[str, Any]:
        routed_via = headers.get("X-Routed-Via") or headers.get("x-routed-via")
        attempts_raw = headers.get("X-Fallback-Attempts") or headers.get("x-fallback-attempts")
        attempts: int | None = None
        if attempts_raw:
            try:
                attempts = int(attempts_raw)
            except (TypeError, ValueError):
                attempts = None
        return {"routed_via": routed_via, "fallback_attempts": attempts}

    async def generate(
        self,
        prompt: str,
        model: str = "auto",
        system: str | None = None,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Single-shot completion through the freellmapi fallback chain.

        Returns dict matching the shape used by other ADA LLM clients:
            {
              "content": str,
              "model": str,
              "input_tokens": int,
              "output_tokens": int,
              "total_tokens": int,
              "cost_usd": 0.0,                  # always 0 — free-tier upstream
              "routed_via": "groq/llama-3.3-70b-versatile" | None,
              "fallback_attempts": int | None,
              "latency_ms": int,
            }
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # freellmapi: omit `model` (or pass non-"auto") so its router auto-picks
        # the highest-priority healthy provider/model from the configured chain.
        # If a specific upstream id is supplied, pin to it.
        if model and model != "auto":
            payload["model"] = model
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # Pass through OpenAI-shape kwargs the caller already prepared
        for k, v in kwargs.items():
            if k.startswith("_"):
                continue
            if k in ("top_p", "response_format", "tools", "tool_choice"):
                payload[k] = v

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                resp = await client.post("/chat/completions", json=payload, headers=self._headers())
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"freellmapi request timed out after {self.timeout_seconds}s: {e}",
            ) from e
        except httpx.ConnectError as e:
            raise ConnectionError(f"freellmapi unreachable at {self.base_url}: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)
        routing = self._extract_routing(resp.headers)

        if resp.status_code >= 400:
            body = resp.text[:300]
            if resp.status_code in (401, 403):
                # Credentials, not capacity: latch the tier off rather than
                # re-paying this round-trip on every subsequent LLM call.
                note_auth_rejected(resp.status_code, self.bearer_token)
            raise RuntimeError(
                f"freellmapi HTTP {resp.status_code} via {routing['routed_via'] or '?'}: {body}"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"freellmapi returned non-JSON body: {e}") from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("freellmapi response had no choices")
        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content") or ""
        if not str(content).strip():
            # Same truncation guard as BifrostProvider._message_content and
            # VLLMProvider.chat -- this is the THIRD path in Zero that
            # substitutes `reasoning` for an empty `content`, and freellmapi
            # routes to whichever free-tier provider is up, so a reasoning model
            # can appear here at any time without warning. Verified live
            # 2026-07-31 immediately after the key rotation: freellmapi routed to
            # zhipu/glm-4.5-flash, which at max_tokens=64 returned
            # content='' and reasoning starting 'Hmm, the user just wants me
            # to reply with exactly "OK"...'. `length` means the budget ran out
            # mid-thought, so there is no answer in the payload and returning
            # the monologue hands the caller the model's thinking as the reply.
            if str(first.get("finish_reason") or "").lower() == "length":
                raise RuntimeError(
                    f"freellmapi response via {routing['routed_via'] or '?'} was "
                    "truncated before any content was produced "
                    "(finish_reason=length); the reasoning block is an "
                    "unfinished internal monologue, not an answer."
                )
            content = (
                message.get("reasoning_content") or message.get("reasoning") or ""
            )

        usage = data.get("usage") or {}
        tokens_input = int(usage.get("prompt_tokens") or 0)
        tokens_output = int(usage.get("completion_tokens") or 0)

        logger.info(
            "freellm_call_ok",
            routed_via=routing["routed_via"],
            fallback_attempts=routing["fallback_attempts"],
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            latency_ms=latency_ms,
        )
        return {
            "content": content,
            "model": data.get("model") or model,
            "input_tokens": tokens_input,
            "output_tokens": tokens_output,
            "total_tokens": tokens_input + tokens_output,
            "cost_usd": 0.0,  # free-tier upstream — budget controls live in the freellmapi dashboard
            "routed_via": routing["routed_via"],
            "fallback_attempts": routing["fallback_attempts"],
            "latency_ms": latency_ms,
        }

    async def health(self) -> dict[str, Any]:
        """Best-effort health snapshot — never raises."""
        # NOTE: `str.rstrip("/v1")` strips CHARACTERS in the set "/v1", which
        # mangles URLs whose port ends in 1 (e.g. "...:3001/v1" gets stripped
        # all the way through 3001's trailing '1'). Use removesuffix() instead.
        root_url = self.base_url
        if root_url.endswith("/v1"):
            root_url = root_url[:-3]
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=root_url, timeout=10.0
            ) as client:
                resp = await client.get("/", headers={"Authorization": f"Bearer {self.bearer_token}"})
                return {
                    "reachable": True,
                    "status_code": resp.status_code,
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                    "base_url": self.base_url,
                }
        except Exception as e:
            return {
                "reachable": False,
                "status_code": None,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "error": str(e)[:200],
                "base_url": self.base_url,
            }


_DEFAULT_CLIENT: FreeLLMAPIClient | None = None


def get_freellm_client() -> FreeLLMAPIClient:
    """Process-singleton FreeLLMAPIClient with env-derived config."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = FreeLLMAPIClient()
    return _DEFAULT_CLIENT
