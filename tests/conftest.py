import pytest

@pytest.fixture(autouse=True)
def setup_test_environment():
    """Global test setup/teardown"""
    # Setup code here
    yield
    # Teardown code here