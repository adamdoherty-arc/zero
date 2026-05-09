import httpx
from httpx import ConnectError

def check_service_availability(url: str) -> bool:
    try:
        response = httpx.get(url, timeout=5.0)
        return response.status_code == 200
    except (ConnectError, httpx.TimeoutException):
        return False