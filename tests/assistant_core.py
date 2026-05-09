import pytest
from zero.assistant_core import process_user_query, generate_response, validate_input

@pytest.mark.parametrize("query, history, expected_error", [
    # Valid case
    ("Hello", [{"role": "user", "content": "Hi"}], None),
    # Empty query
    ("", [{"role": "user", "content": "Hi"}], ValueError),
    # Non-string query
    (123, [{"role": "user", "content": "Hi"}], TypeError),
    # Invalid history type
    ("Hello", "not a list", TypeError),
    # Malformed history entry
    ("Hello", [{"role": "user"}], ValueError),
])
def test_process_user_query_validation(query, history, expected_error):
    if expected_error:
        with pytest.raises(expected_error):
            process_user_query(query, history)
    else:
        assert process_user_query(query, history) is not None

@pytest.mark.parametrize("prompt, max_tokens, temperature, expected_error", [
    # Valid parameters
    ("Sample prompt", 100, 0.7, None),
    # Negative max_tokens
    ("Sample prompt", -10, 0.7, ValueError),
    # Non-integer max_tokens
    ("Sample prompt", "100", 0.7, TypeError),
    # Temperature out of range
    ("Sample prompt", 100, 2.0, ValueError),
    # Non-numeric temperature
    ("Sample prompt", 100, "0.7", TypeError),
    # Empty prompt
    ("", 100, 0.7, ValueError),
])
def test_generate_response_validation(prompt, max_tokens, temperature, expected_error):
    if expected_error:
        with pytest.raises(expected_error):
            generate_response(prompt, max_tokens, temperature)
    else:
        assert generate_response(prompt, max_tokens, temperature) is not None

@pytest.mark.parametrize("input_val, expected_error", [
    # Valid input
    ("Valid string", None),
    # Empty string
    ("", ValueError),
    # Non-string input
    (123, TypeError),
    # None value
    (None, TypeError),
    # Boolean input
    (True, TypeError),
])
def test_validate_input(input_val, expected_error):
    if expected_error:
        with pytest.raises(expected_error):
            validate_input(input_val)
    else:
        assert validate_input(input_val) == input_val

def test_full_coverage_scenarios():
    # Test nested list in history
    with pytest.raises(TypeError):
        process_user_query("Test", [[{"role": "user", "content": "Hi"}]])
    
    # Test generate_response with edge temperature
    assert generate_response("Edge case", 100, 0.0) is not None
    assert generate_response("Edge case", 100, 1.0) is not None
    
    # Test very long input string
    long_input = "a" * 1000
    assert validate_input(long_input) == long_input