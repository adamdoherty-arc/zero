import httpx
import asyncio

async def fetch_weather_data(city):
    url = f"https://api.weatherapi.com/v1/current.json?key=YOUR_API_KEY&q={city}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

async def fetch_news_headlines():
    url = "https://newsapi.org/v2/top-headlines?country=us&apiKey=YOUR_API_KEY"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

# Add other API functions with similar httpx refactoring