import pytest
from unittest import mock
from zero_assistant.utils import check_service_availability

@mock.patch("zero_assistant.utils.httpx.get")
def test_check_service_availability(mock_get):
    mock_response = mock.Mock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    assert check_service_availability("https://example.com") is True
    mock_get.assert_called_once_with("https://example.com", timeout=5.0)

@mock.patch("zero_assistant.utils.httpx.get", side_effect=httpx.ConnectError("Connection failed"))
def test_check_service_availability_failure(mock_get):
    assert check_service_availability("https://example.com") is False
    mock_get.assert_called_once_with("https://example.com", timeout=5.0)