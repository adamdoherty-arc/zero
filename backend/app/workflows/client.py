"""Temporal client connection helper.

Resolves ``ZERO_TEMPORAL_HOST`` from settings and returns a connected
``temporalio.client.Client``. Cached as a module-level singleton because the
underlying gRPC channel is multiplexed across workflows.

Usage::

    client = await get_temporal_client()
    handle = await client.start_workflow(
        GenerateCarouselWorkflow.run,
        payload,
        id=f"carousel-{generation_id}",
        task_queue="carousel-default",
    )
"""

from __future__ import annotations

import os
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


_CLIENT_CACHE: dict[str, object] = {}


async def get_temporal_client(*, namespace: Optional[str] = None):
    """Connect to Temporal once per process.

    Returns a ``temporalio.client.Client``. Raises ``RuntimeError`` if the
    Temporal SDK is not installed (e.g. in a context where carousel V2 is
    not enabled).
    """
    try:
        from temporalio.client import Client  # local import — optional dep
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "temporalio is not installed. Add it to backend/requirements.txt "
            "and rebuild zero-api before enabling ZERO_USE_TEMPORAL."
        ) from exc

    # The Pydantic-aware data converter (temporalio.contrib.pydantic) is
    # required so Pydantic V2 models on the workflow boundary
    # (CarouselWorkflowInput / CarouselWorkflowResult) round-trip through the
    # Temporal payload codec without losing enum values or nested fields.
    # Falls back to the default JSON converter on older SDKs.
    try:
        from temporalio.contrib.pydantic import pydantic_data_converter
        data_converter = pydantic_data_converter
    except Exception:  # noqa: BLE001
        data_converter = None  # default is fine for older SDKs

    target = os.getenv("ZERO_TEMPORAL_HOST", "zero-temporal:7233")
    ns = namespace or os.getenv("ZERO_TEMPORAL_NAMESPACE", "default")
    cache_key = f"{target}::{ns}"

    cached = _CLIENT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if data_converter is not None:
        client = await Client.connect(target, namespace=ns, data_converter=data_converter)
    else:
        client = await Client.connect(target, namespace=ns)
    _CLIENT_CACHE[cache_key] = client
    logger.info("temporal_client_connected", target=target, namespace=ns)
    return client


def use_temporal_enabled() -> bool:
    """Feature flag — only route through Temporal when explicitly enabled."""
    return os.getenv("ZERO_USE_TEMPORAL", "false").strip().lower() in {"1", "true", "yes", "on"}
