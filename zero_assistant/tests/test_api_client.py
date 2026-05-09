import pytest
from unittest import mock
from zero_assistant.api_client import fetch_user_data, async_fetch_user_data

@mock.patch("zero_assistant.api_client.httpx.get")
def test_fetch_user_data(mock_get):
    mock_response = mock.Mock()
    mock_response.json.return_value = {"id": "123", "name": "Test User"}
    mock_get.return_value = mock_response
    
    result = fetch_user_data("123")
    assert result == {"id": "123", "name": "Test User"}
    mock_get.assert_called_once_with(
        "https://api.example.com/users/123",
        timeout=10.0
    )

@mock.patch("zero_assistant.api_client.httpx.AsyncClient")
async def test_async_fetch_user_data(mock_async_client):
    mock_client = mock.Mock()
    mock_response = mock.Mock()
    mock_response.json.return_value = {"id": "123", "name": "Test User"}
    
    mock_client.__aenter__.return_value.get.return_value = mock_response
    mock_async_client.return_value = mock_client
    
    result = await async_fetch_user_data("123")
    assert result == {"id": "123", "name": "Test User"}