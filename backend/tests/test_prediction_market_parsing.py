from app.services.prediction_market_service import _as_float, _as_int, _first_outcome_price


def test_polymarket_numeric_helpers_accept_decimal_strings():
    assert _as_float("50.000009") == 50.000009
    assert _as_int("50.000009") == 50
    assert _as_int(None) == 0


def test_polymarket_outcome_prices_accept_json_string_lists():
    assert _first_outcome_price('["0.42", "0.58"]') == "0.42"
    assert _as_float(_first_outcome_price('["0.42", "0.58"]')) == 0.42
