import pytest
from zero.core import process_data, validate_input

@pytest.fixture
def sample_data():
    """Fixture providing standard test data"""
    return [1, 2, 3, 4, 5]

def test_empty_input():
    """Test handling of empty input"""
    assert process_data([]) == []

def test_boundary_conditions():
    """Test edge value handling"""
    assert process_data([0]) == [0]
    assert process_data([1000]) == [1000]
    assert process_data([-1]) == [-1]

def test_error_scenarios():
    """Test invalid input handling"""
    with pytest.raises(TypeError):
        process_data("invalid")
    with pytest.raises(ValueError):
        process_data([5, "a", 3])

@pytest.mark.parametrize("input_data, expected", [
    ([1, 2, 3], [1, 2, 3]),
    ([10, 20], [10, 20]),
    ([], []),
])
def test_valid_input_handling(input_data, expected):
    """Test valid input scenarios with parametrization"""
    assert process_data(input_data) == expected

def test_validate_input():
    """Test input validation function"""
    assert validate_input([1, 2, 3]) is True
    assert validate_input("string") is False
    assert validate_input([1, "a", 3]) is False

def test_process_data_with_mixed_types():
    """Test handling of mixed type inputs"""
    with pytest.raises(TypeError):
        process_data([1, "two", 3])

def test_large_input_handling():
    """Test with maximum size input"""
    large_input = list(range(1000))
    result = process_data(large_input)
    assert len(result) == 1000
    assert result == large_input

def test_coverage_boundary_case():
    """Test specific coverage boundary condition"""
    assert process_data([None]) == [None]