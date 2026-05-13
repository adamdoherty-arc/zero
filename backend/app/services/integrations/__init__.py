"""
Third-party integrations layer — Composio-backed connectors + auto-fetch.

Architecture mirrors openhuman's: a single provider abstraction
(``composio_provider``) handles OAuth + tool dispatch, and a scheduler
(``auto_fetch_loop``) walks every active connection on a 20-min cadence
pulling fresh data into the Memory Tree.

Composio is optional. If the SDK isn't installed (or the user hasn't
configured an API key), the provider degrades gracefully and lists only
the integrations Zero ships natively (gmail / calendar) instead of crashing
the import chain.
"""

from app.services.integrations.composio_provider import get_composio_provider
from app.services.integrations.auto_fetch_loop import get_auto_fetch_loop

__all__ = ["get_composio_provider", "get_auto_fetch_loop"]
