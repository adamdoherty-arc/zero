"""DEPRECATED 2026-05-18 (S2.5) — /api/prediction-markets removed from Zero.

The router is no longer mounted in ``app/main.py``. Any caller hitting the
old URLs gets a 404. ADA's Unusual Whales pipeline is the canonical data
source — clients should call ADA directly.
"""
from fastapi import APIRouter

# Empty router preserved so an accidental ``from app.routers import
# prediction_markets`` does not crash imports. The router has no routes; any
# call hitting old URLs gets the standard FastAPI 404.
router = APIRouter()
