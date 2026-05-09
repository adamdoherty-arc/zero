# Plan: Kronos Alert Hub Integration — Smart Rule Conditions

## Context

**Kronos Phases 1-6 are COMPLETE and VERIFIED** in production:
- Kronos-base (102M params) running on `cuda:0` — 5 API endpoints live at `/api/kronos/*`
- Frontend: KronosForecastCard (StockDetail), portfolio badges, dashboard widget, chart overlay
- Backend: Advisor, Risk, ML pipeline, portfolio all integrated
- Evaluation: `ml_predictions` tracking, `kronos_evaluator.py`, `kronos_trainer.py` all in place

**User request**: "Is there no way to create alerts off of this? For the alert hub?"

**Goal**: Add Kronos forecast conditions to the Alert Hub smart rules system so users can create alerts based on Kronos predictions (direction changes, confidence thresholds, predicted returns, volatility forecasts).

---

## Architecture Overview

The Alert Hub uses a **ConditionEvaluator** pattern:
1. `ConditionType` enum in [alert_rule_engine.py](backend/services/alert_rule_engine.py) defines all available condition types
2. Each evaluator class extends `ConditionEvaluator` ABC and implements `evaluate(condition, symbol, market_data) -> (is_met, reason, current_values)`
3. Evaluators are registered in `AlertRuleEngine.__init__()` as `self._evaluators["name"]`
4. Routing in `_get_evaluator_for_condition()` maps condition type prefixes to evaluators
5. Smart rule templates in [smart_rule_templates.py](backend/services/smart_rule_templates.py) provide one-click presets

---

## Step 1: Add Kronos ConditionType Entries

**File**: [backend/services/alert_rule_engine.py](backend/services/alert_rule_engine.py) (~line 138, before `CUSTOM`)

Add 6 new condition types:

```python
# Kronos foundation model conditions (Phase 7)
KRONOS_DIRECTION_BULLISH = "kronos_direction_bullish"      # Kronos predicts bullish
KRONOS_DIRECTION_BEARISH = "kronos_direction_bearish"      # Kronos predicts bearish
KRONOS_DIRECTION_CHANGE = "kronos_direction_change"        # Direction flipped since last check
KRONOS_CONFIDENCE_ABOVE = "kronos_confidence_above"        # Model confidence > threshold
KRONOS_PREDICTED_RETURN_ABOVE = "kronos_predicted_return_above"  # Predicted return > X%
KRONOS_VOLATILITY_ABOVE = "kronos_volatility_above"        # Predicted vol > threshold
```

**Why these 6**:
- `DIRECTION_BULLISH` / `DIRECTION_BEARISH` — simple directional alerts ("alert me when Kronos goes bullish on AAPL")
- `DIRECTION_CHANGE` — the most valuable alert ("tell me when the forecast *flips*") using `ml_predictions` history
- `CONFIDENCE_ABOVE` — high-conviction signals only ("only alert when Kronos is >80% confident")
- `PREDICTED_RETURN_ABOVE` — magnitude filter ("only alert when predicted move is >2%")
- `VOLATILITY_ABOVE` — vol alerts ("alert me when Kronos expects high volatility")

## Step 2: Create KronosConditionEvaluator

**File**: [backend/services/alert_rule_engine.py](backend/services/alert_rule_engine.py) (~after `SMAConditionEvaluator`, line ~870)

New evaluator class following the existing pattern:

```python
class KronosConditionEvaluator(ConditionEvaluator):
    """Evaluates Kronos foundation model forecast conditions."""

    async def evaluate(
        self, condition: Condition, symbol: str | None, market_data: dict[str, Any]
    ) -> tuple[bool, str, dict[str, float]]:
        # Lazy import to avoid circular deps
        from backend.services.kronos import get_kronos_service
        kronos = get_kronos_service()

        # Get forecast (uses 5-min cache internally)
        forecast = await kronos.get_forecast_summary(symbol) if symbol else None
        if not forecast:
            return False, f"No Kronos forecast available for {symbol}", {}

        direction = forecast["direction"]
        predicted_return = forecast["predicted_return_pct"]
        confidence = forecast["confidence"]
        volatility = forecast["volatility_forecast"]

        values = {
            "kronos_direction": 1.0 if direction == "bullish" else (-1.0 if direction == "bearish" else 0.0),
            "kronos_predicted_return": predicted_return,
            "kronos_confidence": confidence,
            "kronos_volatility": volatility,
        }

        ctype = condition.type

        if ctype == ConditionType.KRONOS_DIRECTION_BULLISH:
            is_met = direction == "bullish"
            reason = f"Kronos: {direction} ({predicted_return:+.1f}%, {confidence:.0%} conf)"

        elif ctype == ConditionType.KRONOS_DIRECTION_BEARISH:
            is_met = direction == "bearish"
            reason = f"Kronos: {direction} ({predicted_return:+.1f}%, {confidence:.0%} conf)"

        elif ctype == ConditionType.KRONOS_DIRECTION_CHANGE:
            # Check previous prediction from ml_predictions table
            prev_direction = await self._get_previous_direction(symbol)
            changed = prev_direction is not None and prev_direction != direction
            is_met = changed
            values["prev_direction"] = 1.0 if prev_direction == "bullish" else (-1.0 if prev_direction == "bearish" else 0.0)
            reason = f"Kronos direction {'changed' if changed else 'unchanged'}: {prev_direction or '?'} → {direction}"

        elif ctype == ConditionType.KRONOS_CONFIDENCE_ABOVE:
            is_met = confidence >= (condition.value / 100.0) if condition.value > 1 else confidence >= condition.value
            reason = f"Kronos confidence {confidence:.0%} {'≥' if is_met else '<'} {condition.value}%"

        elif ctype == ConditionType.KRONOS_PREDICTED_RETURN_ABOVE:
            is_met = abs(predicted_return) >= condition.value
            reason = f"Kronos predicted return {predicted_return:+.2f}% {'≥' if is_met else '<'} ±{condition.value}%"

        elif ctype == ConditionType.KRONOS_VOLATILITY_ABOVE:
            is_met = volatility >= condition.value
            reason = f"Kronos vol forecast {volatility:.1f}% {'≥' if is_met else '<'} {condition.value}%"

        else:
            return False, f"Unknown Kronos condition: {ctype}", {}

        return is_met, reason, values

    @staticmethod
    async def _get_previous_direction(symbol: str) -> str | None:
        """Get previous Kronos direction from ml_predictions table."""
        try:
            db = await get_database()
            row = await db.fetchrow("""
                SELECT features->>'direction' as direction
                FROM ml_predictions
                WHERE ticker = $1
                  AND model_name = 'kronos-base'
                  AND predicted_at < NOW() - interval '4 hours'
                ORDER BY predicted_at DESC
                LIMIT 1
            """, symbol)
            return row["direction"] if row else None
        except Exception:
            return None
```

**Key design decisions**:
- Uses `get_forecast_summary()` which has 5-min Redis cache — no extra Kronos inference per evaluation
- Direction change detection queries `ml_predictions` (already populated by Phase 6 `_store_prediction()`)
- `_get_previous_direction()` uses `< NOW() - interval '4 hours'` to avoid comparing against the same prediction
- Confidence threshold auto-normalizes: if `value > 1` treats as percentage (e.g., 80 → 0.80)

## Step 3: Register Evaluator & Add Routing

**File**: [backend/services/alert_rule_engine.py](backend/services/alert_rule_engine.py)

1. Add to `self._evaluators` dict (~line 913):
```python
"kronos": KronosConditionEvaluator(),
```

2. Add routing in `_get_evaluator_for_condition()` (~line 1149, before the `else` fallback):
```python
elif ctype.startswith("kronos"):
    return self._evaluators["kronos"]
```

## Step 4: Add Smart Rule Templates

**File**: [backend/services/smart_rule_templates.py](backend/services/smart_rule_templates.py)

Add 3 Kronos templates at the end of the templates list:

```python
# =========================================================================
# Kronos Foundation Model Templates
# =========================================================================
{
    "id": "tpl_kronos_direction_flip",
    "name": "Kronos Direction Reversal",
    "description": "Alert when Kronos AI price forecast flips direction (bullish→bearish or vice versa) with high confidence. Signals potential trend reversal detected by the foundation model.",
    "category": "alert",
    "rule_type": "standard",
    "conditions": {
        "operator": "and",
        "conditions": [
            {"type": "kronos_direction_change", "value": 1},
            {"type": "kronos_confidence_above", "value": 70},
        ],
    },
    "actions": ["notify"],
    "execution_mode": "scheduled",
    "schedule_interval_minutes": 60,
    "cooldown_minutes": 240,
},
{
    "id": "tpl_kronos_high_conviction_bullish",
    "name": "Kronos High-Conviction Bullish",
    "description": "Alert when Kronos predicts bullish with >80% confidence and >2% expected return. Strong buy signal from the AI price forecasting model.",
    "category": "trading",
    "rule_type": "standard",
    "conditions": {
        "operator": "and",
        "conditions": [
            {"type": "kronos_direction_bullish", "value": 1},
            {"type": "kronos_confidence_above", "value": 80},
            {"type": "kronos_predicted_return_above", "value": 2},
        ],
    },
    "actions": ["notify", "recommend"],
    "execution_mode": "scheduled",
    "schedule_interval_minutes": 120,
},
{
    "id": "tpl_kronos_vol_spike_csp",
    "name": "Kronos Volatility + CSP Setup",
    "description": "Combines Kronos high volatility forecast with elevated IV rank for optimal CSP entry. When Kronos predicts vol expansion AND options are already rich, premium selling is most attractive.",
    "category": "trading",
    "rule_type": "hybrid",
    "conditions": {
        "operator": "and",
        "conditions": [
            {"type": "kronos_volatility_above", "value": 30},
            {"type": "iv_rank_above", "value": 50},
            {"type": "kronos_direction_bullish", "value": 1},
        ],
    },
    "actions": ["notify", "recommend"],
    "execution_mode": "scheduled",
    "schedule_interval_minutes": 120,
},
```

## Step 5: Verify `ml_predictions` Has Direction in Features

The `_store_prediction()` method in [kronos_service.py](backend/services/kronos/kronos_service.py) already stores predictions with `features` JSONB. Verify it includes `direction` in the features dict so `_get_previous_direction()` can read it.

If the features column only has `{"timeframe": "1d", "pred_len": 5}`, update `_store_prediction()` to also include `"direction": prediction["direction"]` in the features JSON.

---

## File Summary

| Action | File | Description |
|--------|------|-------------|
| **Edit** | `backend/services/alert_rule_engine.py` | Add 6 `ConditionType` entries, `KronosConditionEvaluator` class, register + route |
| **Edit** | `backend/services/smart_rule_templates.py` | Add 3 Kronos smart rule templates |
| **Edit** | `backend/services/kronos/kronos_service.py` | Ensure `_store_prediction()` includes direction in features JSON |

---

## Execution Order

1. Add `ConditionType` enum entries (5 min)
2. Add `KronosConditionEvaluator` class (10 min)
3. Register evaluator + add routing (2 min)
4. Add smart rule templates (5 min)
5. Verify/fix `_store_prediction()` features JSON (2 min)
6. Docker restart + verify

## Verification Plan

1. `docker restart ada-backend` — confirm no startup errors
2. `curl localhost:8006/api/smart-rules/templates` — confirm 3 new Kronos templates appear
3. Create a test rule via API with `kronos_direction_bullish` condition for a portfolio symbol
4. Trigger evaluation — confirm Kronos evaluator runs and returns forecast data
5. Check `docker logs ada-backend --tail 30` for any errors during evaluation
