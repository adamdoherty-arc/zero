"""DEPRECATED 2026-05-18 (S2.5) — removed from Zero.

ADA's Unusual Whales pipeline is the canonical source for whale and
prediction-market data. The original implementation is archived at
``C:\\code\\Zero\\.archive\\2026-05-18-prediction-market-removal\\prediction_market_service.py``.

This stub raises on import so any missed reference surfaces during boot
rather than silently degrading. Remove the stub once
``grep -ri "prediction_market" C:\\code\\Zero\\backend\\app\\`` returns nothing.
"""
raise ImportError(
    "prediction_market_service was removed on 2026-05-18 (S2.5). "
    "ADA's Unusual Whales pipeline is the sole source of truth for whale / "
    "options-flow / prediction-market data. See "
    "C:\\code\\Zero\\.archive\\2026-05-18-prediction-market-removal\\ for the "
    "original implementation."
)
