"""
Multi-source character image discovery and validation.

Aggregates images from Fandom Wiki, Wikipedia, TMDB, and SearXNG,
validates each for quality (resolution, accessibility), and scores them.
"""

import asyncio
import io
from typing import List, Dict, Any, Optional
from functools import lru_cache

import aiohttp
import structlog

from app.infrastructure.config import get_settings
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()

# Fandom wiki domains by universe
FANDOM_DOMAINS = {
    "marvel": "marvel.fandom.com",
    "dc": "dc.fandom.com",
    "star_wars": "starwars.fandom.com",
    "lotr": "lotr.fandom.com",
    "harry_potter": "harrypotter.fandom.com",
    "disney": "disney.fandom.com",
    "pokemon": "pokemon.fandom.com",
    "one_piece": "onepiece.fandom.com",
    "naruto": "naruto.fandom.com",
    "dragonball": "dragonball.fandom.com",
}

# Source quality tiers for scoring
SOURCE_TIERS = {
    "tmdb": 1.0,
    "fandom": 0.9,
    "wikipedia": 0.8,
    "pexels": 0.7,
    "unsplash": 0.7,
    "pixabay": 0.6,
    "searxng": 0.5,
    "searxng_slide": 0.5,
    "manual": 0.6,
}

# TMDB image base URL
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"


def compute_quality_score(
    width: Optional[int], height: Optional[int], source: str
) -> float:
    """Compute image quality score (0.0 - 1.0)."""
    # Resolution score
    if width and width >= 1080:
        res_score = 1.0
    elif width and width >= 800:
        res_score = 0.7
    elif width and width >= 500:
        res_score = 0.4
    else:
        res_score = 0.1

    # Source tier
    source_score = SOURCE_TIERS.get(source, 0.5)

    # Aspect ratio score (portrait ~3:4 is ideal for TikTok)
    if width and height and width > 0:
        ratio = height / width
        if 1.1 <= ratio <= 1.5:  # Portrait-ish
            ar_score = 1.0
        elif 0.9 <= ratio <= 1.1:  # Square-ish
            ar_score = 0.8
        elif ratio > 1.5:  # Too tall
            ar_score = 0.6
        else:  # Landscape
            ar_score = 0.5
    else:
        ar_score = 0.3

    return round(res_score * 0.4 + source_score * 0.3 + ar_score * 0.3, 3)


class ImageSourceService:
    """Multi-source character image discovery and validation."""

    async def discover_images(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
        max_per_source: int = 10,
    ) -> List[Dict[str, Any]]:
        """Run all image sources in parallel, validate, and return scored results."""
        settings = get_settings()
        tasks = [
            self._safe_source(
                self.source_fandom_images, name, universe, franchise,
            ),
            self._safe_source(
                self.source_wikipedia_images, name, universe,
            ),
            self._safe_source(
                self.source_tmdb_images, name, franchise or universe,
            ),
            self._safe_source(
                self.source_searxng_images, name, universe, franchise,
            ),
        ]
        # Add free image API sources when keys are configured
        if settings.pexels_api_key:
            tasks.append(self._safe_source(
                self.source_pexels_images, name, universe, franchise,
            ))
        if settings.unsplash_access_key:
            tasks.append(self._safe_source(
                self.source_unsplash_images, name, universe, franchise,
            ))
        if settings.pixabay_api_key:
            tasks.append(self._safe_source(
                self.source_pixabay_images, name, universe, franchise,
            ))
        results = await asyncio.gather(*tasks)

        all_images: List[Dict[str, Any]] = []
        seen_urls: set = set()
        for source_images in results:
            for img in source_images[:max_per_source]:
                if img["url"] not in seen_urls:
                    seen_urls.add(img["url"])
                    all_images.append(img)

        # Validate all in parallel (limit concurrency)
        sem = asyncio.Semaphore(5)
        validated: List[Dict[str, Any]] = []

        async def validate(img: Dict) -> None:
            async with sem:
                result = await self._validate_image_url(img["url"])
                if result["is_valid"]:
                    img["width"] = result["width"]
                    img["height"] = result["height"]
                    img["content_type"] = result["content_type"]
                    img["file_size"] = result["file_size"]
                    img["quality_score"] = compute_quality_score(
                        result["width"], result["height"], img["source"],
                    )
                    validated.append(img)

        await asyncio.gather(*[validate(img) for img in all_images])

        # Sort by quality score descending
        validated.sort(key=lambda i: i.get("quality_score", 0), reverse=True)

        logger.info(
            "image_discovery_complete",
            name=name,
            total_found=len(all_images),
            validated=len(validated),
            sources=[img["source"] for img in validated[:5]],
        )
        return validated

    async def _safe_source(self, func, *args) -> List[Dict]:
        """Run a source function safely, returning empty list on error."""
        try:
            return await func(*args)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                ConnectionError, OSError, KeyError, TypeError) as e:
            logger.warning("image_source_failed", source=func.__name__, error=str(e))
            return []

    # ------------------------------------------------------------------
    # Source: Fandom Wiki
    # ------------------------------------------------------------------

    async def source_fandom_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract images from Fandom wiki character pages."""
        domain = FANDOM_DOMAINS.get(universe)
        if not domain and franchise:
            slug = franchise.lower().replace(" ", "").replace("'", "")
            domain = f"{slug}.fandom.com"
        if not domain:
            return []

        wiki_name = name.replace(" ", "_")
        api_url = f"https://{domain}/api.php"
        images: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession() as http:
            # Get the main page image (usually the best one)
            params = {
                "action": "query",
                "titles": wiki_name,
                "prop": "pageimages",
                "piprop": "original",
                "format": "json",
            }
            async with http.get(
                api_url, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for page in pages.values():
                        original = page.get("original", {})
                        img_url = original.get("source")
                        if img_url:
                            images.append({
                                "url": img_url,
                                "source": "fandom",
                                "query_used": f"fandom:{domain}/{wiki_name} (pageimage)",
                            })

            # Get all images on the page
            file_titles: List[str] = []
            params = {
                "action": "query",
                "titles": wiki_name,
                "prop": "images",
                "imlimit": "20",
                "format": "json",
            }
            async with http.get(
                api_url, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for page in pages.values():
                        page_images = page.get("images", [])
                        file_titles = [
                            img["title"] for img in page_images
                            if not any(
                                skip in img.get("title", "").lower()
                                for skip in ["icon", "logo", "flag", "arrow", "button", ".svg"]
                            )
                        ]

            # Get actual URLs for the image files
            for batch_start in range(0, len(file_titles), 5):
                batch = file_titles[batch_start:batch_start + 5]
                params = {
                    "action": "query",
                    "titles": "|".join(batch),
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "format": "json",
                }
                async with http.get(
                    api_url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for page in pages.values():
                            info_list = page.get("imageinfo", [])
                            for info in info_list:
                                img_url = info.get("url", "")
                                w = info.get("width", 0)
                                if img_url and w >= 400:
                                    images.append({
                                        "url": img_url,
                                        "source": "fandom",
                                        "query_used": f"fandom:{domain}/{page.get('title', '')}",
                                    })

        logger.debug("fandom_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Wikipedia
    # ------------------------------------------------------------------

    async def source_wikipedia_images(
        self, name: str, universe: str,
    ) -> List[Dict[str, Any]]:
        """Extract images from Wikipedia character articles."""
        wiki_name = name.replace(" ", "_")
        # Try character-specific title first, then generic
        titles_to_try = [
            f"{wiki_name}_(character)",
            f"{wiki_name}_({universe})",
            wiki_name,
        ]

        images: List[Dict[str, Any]] = []
        async with aiohttp.ClientSession() as http:
            for title in titles_to_try:
                url = f"https://en.wikipedia.org/api/rest_v1/page/media-list/{title}"
                try:
                    async with http.get(
                        url, timeout=aiohttp.ClientTimeout(total=10),
                        headers={"User-Agent": "ZeroBot/1.0 (image research)"},
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        items = data.get("items", [])
                        for item in items:
                            if item.get("type") != "image":
                                continue
                            src_set = item.get("srcset", [])
                            # Get highest resolution version
                            best_url = None
                            best_scale = 0
                            for src in src_set:
                                scale = src.get("scale", "1x")
                                scale_num = float(scale.replace("x", "")) if isinstance(scale, str) else 1
                                if scale_num > best_scale:
                                    best_scale = scale_num
                                    best_url = src.get("src")
                            if not best_url:
                                # Fall back to original
                                original = item.get("original", {})
                                best_url = original.get("source")
                            if best_url:
                                # Wikipedia URLs may start with //
                                if best_url.startswith("//"):
                                    best_url = f"https:{best_url}"
                                images.append({
                                    "url": best_url,
                                    "source": "wikipedia",
                                    "query_used": f"wikipedia:{title}",
                                })
                        if images:
                            break  # Found images, stop trying titles
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    continue

        logger.debug("wikipedia_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: TMDB (The Movie Database)
    # ------------------------------------------------------------------

    async def source_tmdb_images(
        self, name: str, franchise: str,
    ) -> List[Dict[str, Any]]:
        """Search TMDB for movie/TV show images related to character."""
        settings = get_settings()
        # Prefer Bearer token (Read Access Token), fall back to API key
        access_token = settings.tmdp_read_access_token
        api_key = settings.tmdp_api_key
        if not access_token and not api_key:
            return []

        images: List[Dict[str, Any]] = []
        base = "https://api.themoviedb.org/3"
        if access_token:
            headers = {"Authorization": f"Bearer {access_token}"}
        else:
            headers = {}

        # If using API key instead of Bearer token, add it to all requests
        base_params = {"api_key": api_key} if (api_key and not access_token) else {}

        async with aiohttp.ClientSession() as http:
            # Search for the franchise/movie/show
            search_url = f"{base}/search/multi"
            params = {**base_params, "query": franchise, "language": "en-US", "page": 1}
            async with http.get(
                search_url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = data.get("results", [])

            # Get images for the top 2 results
            for item in results[:2]:
                media_type = item.get("media_type", "movie")
                media_id = item.get("id")
                if not media_id:
                    continue

                img_url = f"{base}/{media_type}/{media_id}/images"
                async with http.get(
                    img_url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                    # Backdrops (1920x1080 landscape stills)
                    for backdrop in data.get("backdrops", [])[:8]:
                        file_path = backdrop.get("file_path")
                        if file_path:
                            images.append({
                                "url": f"{TMDB_IMAGE_BASE}{file_path}",
                                "source": "tmdb",
                                "query_used": f"tmdb:{media_type}/{media_id}/backdrop",
                            })

                    # Posters (portrait format, ideal for TikTok)
                    for poster in data.get("posters", [])[:5]:
                        file_path = poster.get("file_path")
                        if file_path:
                            images.append({
                                "url": f"{TMDB_IMAGE_BASE}{file_path}",
                                "source": "tmdb",
                                "query_used": f"tmdb:{media_type}/{media_id}/poster",
                            })

            # Also search for the actor/person
            person_url = f"{base}/search/person"
            params = {**base_params, "query": name, "language": "en-US", "page": 1}
            async with http.get(
                person_url, params=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for person in data.get("results", [])[:1]:
                        person_id = person.get("id")
                        if not person_id:
                            continue
                        # Get person's tagged images (character stills)
                        tagged_url = f"{base}/person/{person_id}/tagged_images"
                        async with http.get(
                            tagged_url, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp2:
                            if resp2.status == 200:
                                data2 = await resp2.json()
                                for tagged in data2.get("results", [])[:5]:
                                    file_path = tagged.get("file_path")
                                    if file_path:
                                        images.append({
                                            "url": f"{TMDB_IMAGE_BASE}{file_path}",
                                            "source": "tmdb",
                                            "query_used": f"tmdb:person/{person_id}/tagged",
                                        })

        logger.debug("tmdb_images", name=name, franchise=franchise, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: SearXNG (improved queries)
    # ------------------------------------------------------------------

    async def source_searxng_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Enhanced SearXNG image search with better queries."""
        searxng = get_searxng_service()
        fran = franchise or universe
        queries = [
            f"{name} {fran} official HD movie still",
            f"{name} {fran} cinematic 4K wallpaper",
            f"{name} {universe} character portrait high resolution",
            f"{name} {fran} promotional photo official",
            f"{name} {universe} scene screenshot HD",
        ]

        images: List[Dict[str, Any]] = []
        seen: set = set()
        for query in queries:
            try:
                results = await searxng.search(query, num_results=5, categories=["images"])
                for r in results:
                    img_url = (
                        getattr(r, "img_src", None) or getattr(r, "url", None)
                        or (r.get("img_src") if isinstance(r, dict) else None)
                        or (r.get("url") if isinstance(r, dict) else "")
                    )
                    if not img_url or not img_url.startswith("http"):
                        continue
                    if img_url in seen:
                        continue
                    seen.add(img_url)
                    images.append({
                        "url": img_url,
                        "source": "searxng",
                        "query_used": query,
                    })
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError):
                continue

        logger.debug("searxng_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Pexels
    # ------------------------------------------------------------------

    async def source_pexels_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search Pexels for character-related images."""
        settings = get_settings()
        if not settings.pexels_api_key:
            return []

        fran = franchise or universe
        query = f"{name} {fran}"
        images: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": settings.pexels_api_key},
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for photo in data.get("photos", []):
                    if photo.get("width", 0) >= 800:
                        images.append({
                            "url": photo["src"]["large2x"],
                            "source": "pexels",
                            "query_used": f"pexels:{query}",
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                        })

        logger.debug("pexels_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Unsplash
    # ------------------------------------------------------------------

    async def source_unsplash_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search Unsplash for character-related images."""
        settings = get_settings()
        if not settings.unsplash_access_key:
            return []

        fran = franchise or universe
        query = f"{name} {fran}"
        images: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://api.unsplash.com/search/photos",
                headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for result in data.get("results", []):
                    if result.get("width", 0) >= 800:
                        images.append({
                            "url": result["urls"]["regular"],
                            "source": "unsplash",
                            "query_used": f"unsplash:{query}",
                            "width": result.get("width"),
                            "height": result.get("height"),
                        })

        logger.debug("unsplash_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Pixabay
    # ------------------------------------------------------------------

    async def source_pixabay_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search Pixabay for character-related images."""
        settings = get_settings()
        if not settings.pixabay_api_key:
            return []

        fran = franchise or universe
        query = f"{name} {fran}"
        images: List[Dict[str, Any]] = []

        async with aiohttp.ClientSession() as http:
            async with http.get(
                "https://pixabay.com/api/",
                params={
                    "key": settings.pixabay_api_key,
                    "q": query,
                    "per_page": 15,
                    "image_type": "photo",
                    "min_width": 800,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for hit in data.get("hits", []):
                    images.append({
                        "url": hit.get("largeImageURL", hit.get("webformatURL", "")),
                        "source": "pixabay",
                        "query_used": f"pixabay:{query}",
                        "width": hit.get("imageWidth"),
                        "height": hit.get("imageHeight"),
                    })

        logger.debug("pixabay_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def _validate_image_url(self, url: str) -> Dict[str, Any]:
        """HTTP HEAD + partial download to validate image URL and extract dimensions."""
        result: Dict[str, Any] = {
            "is_valid": False, "width": None, "height": None,
            "content_type": None, "file_size": 0,
        }
        try:
            async with aiohttp.ClientSession() as http:
                async with http.head(
                    url, timeout=aiohttp.ClientTimeout(total=8),
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        return result
                    ct = resp.headers.get("content-type", "")
                    if not ct.startswith("image/"):
                        return result
                    result["content_type"] = ct
                    cl = resp.headers.get("content-length")
                    if cl:
                        result["file_size"] = int(cl)

                async with http.get(
                    url, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return result
                    chunk = await resp.content.read(65536)

            from PIL import Image
            img = Image.open(io.BytesIO(chunk))
            result["width"] = img.width
            result["height"] = img.height
            result["is_valid"] = img.width >= 800
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            pass
        return result


@lru_cache()
def get_image_source_service() -> ImageSourceService:
    return ImageSourceService()
