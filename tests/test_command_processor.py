import pytest
from processing.command_processor import process_command

def test_error_handling():
    """
    Test that the command processor handles errors gracefully
    """
    # Test with invalid input that would cause exceptions in lower-level code
    result = process_command(None, {})
    assert result is None

    result = process_command("some command", {"bad_key": "value"})
    assert result is not None  # Should not raise exceptions

    # Test with very long string that might cause memory issues
    long_string = "a" * 1000000
    result = process_command(long_string, {})
    assert result is not None