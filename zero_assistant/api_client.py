import httpx
from httpx import HTTPStatusError

def fetch_user_data(user_id: str) -> dict:
    url = f"https://api.example.com/users/{user_id}"
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except HTTPStatusError as e:
        print(f"API request failed: {e}")
        raise

async def async_fetch_user_data(user_id: str) -> dict:
    url = f"https://api.example.com/users/{user_id}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except HTTPStatusError as e:
            print(f"Async API request failed: {e}")
            raise