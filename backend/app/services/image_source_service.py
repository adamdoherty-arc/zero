"""
Multi-source character image discovery and validation.

Aggregates images from Fandom Wiki, Wikipedia, TMDB, and SearXNG,
validates each for quality (resolution, accessibility), and scores them.
"""

import asyncio
import io
import time
from typing import List, Dict, Any, Optional
from functools import lru_cache

import aiohttp
import structlog
from PIL import ImageFile

# Validator reads only the first 64KB of each image to keep HEAD+GET fast.
# PIL's default is strict: `img.load()` raises OSError on any truncated payload,
# which rejects every real-world JPEG >64KB. Tolerating truncation lets us
# read width/height from the header (always in the first few KB) and get
# best-effort pixels for perceptual hashing / face detection.
ImageFile.LOAD_TRUNCATED_IMAGES = True

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
    # Additional sources
    "bing_images": 0.6,
    "duckduckgo_images": 0.55,
    "youtube_thumbnail": 0.6,
    "reddit": 0.55,
    "commons": 0.75,
    "giphy": 0.5,
    "flickr": 0.6,
    "omdb": 0.7,
    "deviantart": 0.5,
    "artstation": 0.55,
    "user_upload": 1.0,
    # Niche character sources
    "comicvine": 0.85,
    "fanart_tv": 0.85,
    "thetvdb": 0.8,
    "giant_bomb": 0.8,
    "jikan": 0.8,
    "superhero_api": 0.75,
}

# TheTVDB v4 bearer token cache (1h expiry)
_THETVDB_TOKEN: Dict[str, Any] = {"token": None, "expires_at": 0.0}

# TMDB image base URL
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"


def compute_quality_score(
    width: Optional[int], height: Optional[int], source: str,
    face_present: bool = False,
    safe_zone_score: float = 0.0,
    centered_score: float = 0.0,
    relevance: Optional[float] = None,
) -> float:
    """Compute image quality score (0.0 - 1.0).

    Blends resolution, source tier, aspect ratio, face presence, and a
    rough text-overlay safe-zone score (darker/low-variance bottom third).

    When ``relevance`` is provided (0.0-1.0 from vision validation), it's
    applied as a multiplier with a 0.4 floor: a fully-irrelevant image
    keeps 40% of its prior score (correctly demoted but not zeroed in case
    of a false-negative vision call), a perfect match keeps 100%.
    """
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
        if 1.1 <= ratio <= 1.5:
            ar_score = 1.0
        elif 0.9 <= ratio <= 1.1:
            ar_score = 0.8
        elif ratio > 1.5:
            ar_score = 0.6
        else:
            ar_score = 0.5
    else:
        ar_score = 0.3

    base = res_score * 0.32 + source_score * 0.22 + ar_score * 0.22
    face_bonus = 0.12 if face_present else 0.0
    safe_bonus = max(0.0, min(safe_zone_score, 1.0)) * 0.06
    center_bonus = max(0.0, min(centered_score, 1.0)) * 0.06
    raw = base + face_bonus + safe_bonus + center_bonus

    if relevance is not None:
        rel = max(0.0, min(1.0, float(relevance)))
        raw = raw * (0.4 + 0.6 * rel)

    return round(min(1.0, raw), 3)


def _compute_quality_signals(pil_img) -> Dict[str, Any]:
    """Compute face-presence + safe-zone + centered-subject signals.

    Fails gracefully if OpenCV/numpy aren't installed — returns zeros.
    """
    out: Dict[str, Any] = {
        "face_present": False, "safe_zone_score": 0.0, "centered_score": 0.0,
    }
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return out
    try:
        rgb = pil_img.convert("RGB")
        arr = np.asarray(rgb)
        h, w, _ = arr.shape
        # Brightness-based variance in bottom third (low variance == safe for
        # overlay text). Using grayscale to keep this fast.
        gray = (0.299 * arr[..., 0] + 0.587 * arr[..., 1]
                + 0.114 * arr[..., 2]).astype("float32")
        bottom = gray[int(h * 0.66):, :]
        if bottom.size:
            var = float(bottom.std())
            # Map 0..60 std -> 1..0 safe-zone score.
            out["safe_zone_score"] = max(0.0, min(1.0, 1.0 - var / 60.0))
        # Centered subject heuristic: center region brightness vs. edges.
        cy0, cy1 = int(h * 0.2), int(h * 0.8)
        cx0, cx1 = int(w * 0.2), int(w * 0.8)
        if cy1 > cy0 and cx1 > cx0:
            center_mean = float(gray[cy0:cy1, cx0:cx1].mean())
            edge_sum = (
                float(gray[:cy0, :].mean()) + float(gray[cy1:, :].mean())
                + float(gray[:, :cx0].mean()) + float(gray[:, cx1:].mean())
            ) / 4.0
            # Lower edges vs center == more centered subject.
            diff = (center_mean - edge_sum) / 255.0
            out["centered_score"] = max(0.0, min(1.0, diff + 0.3))
    except (ValueError, ArithmeticError):
        pass

    # Face detection (OpenCV Haar cascade).
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        rgb = pil_img.convert("RGB")
        arr = np.asarray(rgb)
        gray_cv = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cascade_path = (
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        cascade = cv2.CascadeClassifier(cascade_path)
        if not cascade.empty():
            faces = cascade.detectMultiScale(
                gray_cv, scaleFactor=1.2, minNeighbors=4,
                minSize=(40, 40),
            )
            out["face_present"] = bool(len(faces) > 0)
    except (ImportError, ValueError, OSError):
        pass
    return out


def _hamming(a: str, b: str) -> int:
    """Hamming distance between two hex pHash strings."""
    if not a or not b or len(a) != len(b):
        return 64
    try:
        ai = int(a, 16)
        bi = int(b, 16)
    except ValueError:
        return 64
    return bin(ai ^ bi).count("1")


class ImageSourceService:
    """Multi-source character image discovery and validation."""

    async def discover_images(
        self,
        name: str,
        universe: str,
        franchise: Optional[str] = None,
        max_per_source: int = 10,
        relevance_top_n: int = 8,
        description: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run all image sources in parallel, validate, and return scored results.

        ``relevance_top_n`` candidates are validated against the character
        identity via Gemini Vision after the initial quality sort but before
        pHash dedup, so a sharp 1080p photo of the wrong character gets
        demoted before it crowds out a softer correct one. Set to 0 to skip
        vision (e.g., for tests).
        """
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
            # Free SearXNG-backed sources (no key required)
            self._safe_source(
                self.source_bing_images, name, universe, franchise,
            ),
            self._safe_source(
                self.source_duckduckgo_images, name, universe, franchise,
            ),
            self._safe_source(
                self.source_youtube_thumbnails, name, universe, franchise,
            ),
            self._safe_source(
                self.source_reddit_images, name, universe, franchise,
            ),
            self._safe_source(
                self.source_mediawiki_commons, name,
            ),
            self._safe_source(
                self.source_artstation_images, name,
            ),
            self._safe_source(
                self.source_deviantart_images, name,
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
        if settings.giphy_api_key:
            tasks.append(self._safe_source(
                self.source_giphy_images, name,
            ))
        if settings.flickr_api_key:
            tasks.append(self._safe_source(
                self.source_flickr_images, name, universe,
            ))
        if settings.omdb_api_key:
            tasks.append(self._safe_source(
                self.source_omdb_posters, name, universe,
            ))
        if settings.comicvine_api_key:
            tasks.append(self._safe_source(
                self.source_comicvine_images, name, universe, franchise,
            ))
        if settings.fanart_api_key:
            tasks.append(self._safe_source(
                self.source_fanart_tv_images, name, universe, franchise,
            ))
        if settings.thetvdb_api_key:
            tasks.append(self._safe_source(
                self.source_thetvdb_images, name, universe, franchise,
            ))
        if settings.giant_bomb_api_key:
            tasks.append(self._safe_source(
                self.source_giant_bomb_images, name, universe, franchise,
            ))
        # Jikan: no key required, but method self-gates on anime hints
        tasks.append(self._safe_source(
            self.source_jikan_anime_images, name, universe, franchise,
        ))
        if settings.superhero_api_key:
            tasks.append(self._safe_source(
                self.source_superhero_api_images, name, universe, franchise,
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
                    img["phash"] = result.get("phash")
                    img["sha256"] = result.get("sha256")
                    img["face_present"] = result.get("face_present", False)
                    img["safe_zone_score"] = result.get("safe_zone_score", 0.0)
                    img["centered_score"] = result.get("centered_score", 0.0)
                    img["quality_score"] = compute_quality_score(
                        result["width"], result["height"], img["source"],
                        face_present=img["face_present"],
                        safe_zone_score=img["safe_zone_score"],
                        centered_score=img["centered_score"],
                    )
                    validated.append(img)

        await asyncio.gather(*[validate(img) for img in all_images])

        # Sort by quality score descending
        validated.sort(key=lambda i: i.get("quality_score", 0), reverse=True)

        # Vision relevance: validate the top-N candidates against character
        # identity, then re-score with relevance as a multiplier and re-sort.
        # This is the fix for the "Thor failure mode" — a sharp 1080p photo
        # of the wrong character was previously winning on resolution + face
        # bonuses alone.
        if relevance_top_n > 0 and validated:
            await self._apply_relevance_scoring(
                validated[:relevance_top_n],
                name=name, universe=universe, franchise=franchise,
                description=description,
            )
            validated.sort(key=lambda i: i.get("quality_score", 0), reverse=True)

        # Perceptual-hash dedup: keep the higher-scoring of any near-dupes
        # (Hamming distance <= 6 on 64-bit pHash).
        kept: List[Dict[str, Any]] = []
        for img in validated:
            ph = img.get("phash")
            if not ph:
                kept.append(img)
                continue
            dup = False
            for existing in kept:
                eph = existing.get("phash")
                if not eph:
                    continue
                if _hamming(ph, eph) <= 6:
                    dup = True
                    break
            if not dup:
                kept.append(img)
        if len(kept) < len(validated):
            logger.info(
                "image_phash_dedup",
                name=name,
                before=len(validated), after=len(kept),
            )
        validated = kept

        logger.info(
            "image_discovery_complete",
            name=name,
            total_found=len(all_images),
            validated=len(validated),
            sources=[img["source"] for img in validated[:5]],
        )
        return validated

    async def _apply_relevance_scoring(
        self,
        images: List[Dict[str, Any]],
        *,
        name: str,
        universe: str,
        franchise: Optional[str],
        description: Optional[str],
    ) -> None:
        """Run Gemini Vision relevance check on each image and update its
        ``quality_score`` in place using the relevance multiplier.

        Mutates each img dict to add ``relevance_score`` and
        ``relevance_reason`` (and ``relevance_source`` for traceability).
        """
        try:
            from app.services.character_image_relevance_service import (
                get_character_image_relevance_service,
            )
        except ImportError:
            return

        relevance_service = get_character_image_relevance_service()

        async def _score(img: Dict[str, Any]) -> None:
            result = await relevance_service.score_relevance(
                image_url=img["url"],
                character_name=name,
                universe=universe,
                franchise=franchise,
                description=description,
            )
            img["relevance_score"] = result["score"]
            img["relevance_reason"] = result["reason"]
            img["relevance_source"] = result["source"]
            img["relevance_is_match"] = result["is_match"]
            # Only apply the relevance multiplier when vision actually
            # answered. ``vision_unavailable`` keeps the historical score so
            # an outage never demotes a candidate.
            apply_relevance = result["source"] == "vision"
            img["quality_score"] = compute_quality_score(
                img.get("width"), img.get("height"), img["source"],
                face_present=img.get("face_present", False),
                safe_zone_score=img.get("safe_zone_score", 0.0),
                centered_score=img.get("centered_score", 0.0),
                relevance=result["score"] if apply_relevance else None,
            )

        await asyncio.gather(*[_score(img) for img in images], return_exceptions=True)
        rejected = sum(1 for i in images if i.get("relevance_score", 0.5) < 0.3)
        logger.info(
            "image_relevance_scored",
            name=name, total=len(images), rejected=rejected,
        )

    async def _safe_source(self, func, *args) -> List[Dict]:
        """Run a source function safely, returning empty list on error.

        Tracks per-source success/failure counts on the service instance so the
        daily report can flag chronically failing or empty sources.
        """
        if not hasattr(self, "_source_health"):
            self._source_health: Dict[str, Dict[str, int]] = {}
        bucket = self._source_health.setdefault(func.__name__, {"success": 0, "failure": 0, "empty": 0})
        try:
            results = await func(*args)
            if results:
                bucket["success"] += 1
            else:
                bucket["empty"] += 1
            return results
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                ConnectionError, OSError, KeyError, TypeError) as e:
            bucket["failure"] += 1
            logger.warning(
                "image_source_failed",
                source=func.__name__,
                error=str(e),
                failure_count=bucket["failure"],
                success_count=bucket["success"],
            )
            return []

    def get_source_health(self) -> Dict[str, Dict[str, int]]:
        """Return per-source counters since process start. Used by daily report."""
        return dict(getattr(self, "_source_health", {}))

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
    # Source: SearXNG-backed (Bing / DuckDuckGo / YouTube / Reddit)
    # ------------------------------------------------------------------

    async def _searxng_engine_search(
        self, query: str, engines: str, categories: Optional[List[str]] = None,
        num_results: int = 10,
    ) -> List[Any]:
        """Call SearXNG with a specific engines filter via params override."""
        searxng = get_searxng_service()
        try:
            # Reuse the underlying HTTP client but pass engines explicitly
            params = {
                "q": query,
                "format": "json",
                "pageno": 1,
                "engines": engines,
            }
            if categories:
                params["categories"] = ",".join(categories)
            response = await searxng.client.get(
                f"{searxng.base_url}/search", params=params,
            )
            if response.status_code != 200:
                return []
            data = response.json()
            return data.get("results", [])[:num_results]
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.debug("searxng_engine_failed", engines=engines, error=str(e))
            return []
        except Exception as e:  # noqa: BLE001 - httpx errors
            logger.debug("searxng_engine_failed", engines=engines, error=str(e))
            return []

    async def source_bing_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Bing Images via SearXNG engine override."""
        fran = franchise or universe
        query = f"{name} {fran} character"
        images: List[Dict[str, Any]] = []
        try:
            results = await self._searxng_engine_search(
                query, engines="bing images", categories=["images"],
                num_results=15,
            )
            seen: set = set()
            for r in results:
                img_url = r.get("img_src") or r.get("url") or ""
                if not img_url or not img_url.startswith("http"):
                    continue
                if img_url in seen:
                    continue
                seen.add(img_url)
                images.append({
                    "url": img_url,
                    "source": "bing_images",
                    "query_used": f"bing:{query}",
                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("bing_images", name=name, count=len(images))
        return images

    async def source_duckduckgo_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """DuckDuckGo Images via SearXNG engine override."""
        fran = franchise or universe
        query = f"{name} {fran} character"
        images: List[Dict[str, Any]] = []
        try:
            results = await self._searxng_engine_search(
                query, engines="duckduckgo images", categories=["images"],
                num_results=15,
            )
            seen: set = set()
            for r in results:
                img_url = r.get("img_src") or r.get("url") or ""
                if not img_url or not img_url.startswith("http"):
                    continue
                if img_url in seen:
                    continue
                seen.add(img_url)
                images.append({
                    "url": img_url,
                    "source": "duckduckgo_images",
                    "query_used": f"ddg:{query}",
                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("duckduckgo_images", name=name, count=len(images))
        return images

    async def source_youtube_thumbnails(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract YouTube video thumbnails via SearXNG YouTube engine."""
        fran = franchise or universe
        query = f"{name} {fran} scene"
        images: List[Dict[str, Any]] = []
        try:
            results = await self._searxng_engine_search(
                query, engines="youtube", categories=["videos"],
                num_results=15,
            )
            seen: set = set()
            for r in results:
                # SearXNG youtube results include a thumbnail field, plus URL
                vid_id: Optional[str] = None
                url = r.get("url") or ""
                if "youtube.com/watch" in url and "v=" in url:
                    try:
                        vid_id = url.split("v=")[1].split("&")[0]
                    except (IndexError, AttributeError):
                        vid_id = None
                elif "youtu.be/" in url:
                    try:
                        vid_id = url.split("youtu.be/")[1].split("?")[0]
                    except (IndexError, AttributeError):
                        vid_id = None
                if vid_id:
                    img_url = (
                        f"https://i.ytimg.com/vi/{vid_id}/maxresdefault.jpg"
                    )
                    if img_url in seen:
                        continue
                    seen.add(img_url)
                    images.append({
                        "url": img_url,
                        "source": "youtube_thumbnail",
                        "query_used": f"youtube:{query}",
                    })
                else:
                    # Fall back to embedded thumbnail if present
                    thumb = r.get("thumbnail") or r.get("img_src")
                    if thumb and thumb.startswith("http") and thumb not in seen:
                        seen.add(thumb)
                        images.append({
                            "url": thumb,
                            "source": "youtube_thumbnail",
                            "query_used": f"youtube:{query}",
                        })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("youtube_thumbnails", name=name, count=len(images))
        return images

    async def source_reddit_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Reddit images via SearXNG Reddit engine."""
        fran = franchise or universe
        query = f"{name} {fran}"
        images: List[Dict[str, Any]] = []
        try:
            results = await self._searxng_engine_search(
                query, engines="reddit", num_results=20,
            )
            seen: set = set()
            for r in results:
                candidates = []
                for key in ("img_src", "thumbnail", "url"):
                    v = r.get(key)
                    if v:
                        candidates.append(v)
                for img_url in candidates:
                    if not isinstance(img_url, str):
                        continue
                    if not img_url.startswith("http"):
                        continue
                    if "i.redd.it" not in img_url and "preview.redd.it" not in img_url:
                        continue
                    if img_url in seen:
                        continue
                    seen.add(img_url)
                    images.append({
                        "url": img_url,
                        "source": "reddit",
                        "query_used": f"reddit:{query}",
                    })
                    break
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("reddit_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Wikimedia Commons
    # ------------------------------------------------------------------

    async def source_mediawiki_commons(
        self, name: str,
    ) -> List[Dict[str, Any]]:
        """Search Wikimedia Commons for freely licensed images."""
        images: List[Dict[str, Any]] = []
        api_url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": name,
            "gsrlimit": "10",
            "gsrnamespace": "6",  # File namespace
            "prop": "imageinfo",
            "iiprop": "url|size",
            "format": "json",
        }
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    api_url, params=params,
                    headers={"User-Agent": "ZeroBot/1.0 (image research)"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for page in pages.values():
                        info_list = page.get("imageinfo", [])
                        for info in info_list:
                            img_url = info.get("url", "")
                            w = info.get("width", 0) or 0
                            if img_url and w >= 500:
                                images.append({
                                    "url": img_url,
                                    "source": "commons",
                                    "query_used": f"commons:{name}",
                                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("commons_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Giphy (requires key)
    # ------------------------------------------------------------------

    async def source_giphy_images(
        self, name: str,
    ) -> List[Dict[str, Any]]:
        """Search Giphy for GIFs."""
        settings = get_settings()
        if not settings.giphy_api_key:
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://api.giphy.com/v1/gifs/search",
                    params={
                        "api_key": settings.giphy_api_key,
                        "q": name,
                        "limit": 10,
                        "rating": "pg-13",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for item in data.get("data", []):
                        orig = item.get("images", {}).get("original", {})
                        img_url = orig.get("url")
                        if img_url:
                            images.append({
                                "url": img_url,
                                "source": "giphy",
                                "query_used": f"giphy:{name}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("giphy_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Flickr (requires key)
    # ------------------------------------------------------------------

    async def source_flickr_images(
        self, name: str, universe: str,
    ) -> List[Dict[str, Any]]:
        """Search Flickr for photos."""
        settings = get_settings()
        if not settings.flickr_api_key:
            return []
        query = f"{name} {universe}"
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://www.flickr.com/services/rest/",
                    params={
                        "method": "flickr.photos.search",
                        "api_key": settings.flickr_api_key,
                        "text": query,
                        "format": "json",
                        "nojsoncallback": "1",
                        "safe_search": "2",
                        "content_types": "0",
                        "sort": "relevance",
                        "per_page": "10",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for photo in data.get("photos", {}).get("photo", []):
                        server = photo.get("server")
                        pid = photo.get("id")
                        secret = photo.get("secret")
                        if server and pid and secret:
                            img_url = (
                                f"https://live.staticflickr.com/"
                                f"{server}/{pid}_{secret}_b.jpg"
                            )
                            images.append({
                                "url": img_url,
                                "source": "flickr",
                                "query_used": f"flickr:{query}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("flickr_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: OMDb posters (requires key)
    # ------------------------------------------------------------------

    async def source_omdb_posters(
        self, name: str, universe: str,
    ) -> List[Dict[str, Any]]:
        """Search OMDb for movie/show posters."""
        settings = get_settings()
        if not settings.omdb_api_key:
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://www.omdbapi.com/",
                    params={
                        "apikey": settings.omdb_api_key,
                        "s": name,
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for item in data.get("Search", []) or []:
                        poster = item.get("Poster")
                        if poster and poster != "N/A" and poster.startswith("http"):
                            images.append({
                                "url": poster,
                                "source": "omdb",
                                "query_used": f"omdb:{name}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("omdb_posters", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: ComicVine (key-gated)
    # ------------------------------------------------------------------

    async def source_comicvine_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """ComicVine character search (key-gated)."""
        settings = get_settings()
        if not settings.comicvine_api_key:
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://comicvine.gamespot.com/api/search/",
                    params={
                        "api_key": settings.comicvine_api_key,
                        "format": "json",
                        "resources": "character",
                        "query": name,
                        "limit": 5,
                    },
                    headers={"User-Agent": "Zero/1.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for r in data.get("results", []) or []:
                        img = r.get("image") or {}
                        for key in ("super_url", "screen_large_url"):
                            u = img.get(key)
                            if u and isinstance(u, str) and u.startswith("http"):
                                images.append({
                                    "url": u,
                                    "source": "comicvine",
                                    "query_used": f"comicvine:{name}",
                                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("comicvine_failed", name=name, error=str(e))
            return []
        logger.debug("comicvine_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Fanart.tv (TMDB-ID-dependent, key-gated)
    # ------------------------------------------------------------------

    async def source_fanart_tv_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fanart.tv art, keyed off a TMDB ID found via TMDB multi-search."""
        settings = get_settings()
        if not settings.fanart_api_key:
            return []
        access_token = settings.tmdp_read_access_token
        api_key = settings.tmdp_api_key
        if not access_token and not api_key:
            return []

        images: List[Dict[str, Any]] = []
        try:
            tmdb_headers = (
                {"Authorization": f"Bearer {access_token}"}
                if access_token else {}
            )
            tmdb_params: Dict[str, Any] = {
                "query": franchise or universe or name,
                "language": "en-US", "page": 1,
            }
            if not access_token and api_key:
                tmdb_params["api_key"] = api_key

            tmdb_id: Optional[int] = None
            media_type: Optional[str] = None
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://api.themoviedb.org/3/search/multi",
                    params=tmdb_params, headers=tmdb_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for item in data.get("results", [])[:1]:
                        tmdb_id = item.get("id")
                        mt = item.get("media_type", "movie")
                        media_type = "tv" if mt == "tv" else "movies"
                if not tmdb_id or not media_type:
                    return []

                url = f"https://webservice.fanart.tv/v3/{media_type}/{tmdb_id}"
                async with http.get(
                    url, params={"api_key": settings.fanart_api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for key in (
                        "hdmovielogo", "moviebackground", "movieposter",
                        "hdtvlogo", "showbackground", "tvposter",
                    ):
                        for entry in data.get(key, []) or []:
                            u = entry.get("url")
                            if u and isinstance(u, str) and u.startswith("http"):
                                images.append({
                                    "url": u,
                                    "source": "fanart_tv",
                                    "query_used": (
                                        f"fanart_tv:{media_type}/{tmdb_id}"
                                    ),
                                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("fanart_tv_failed", name=name, error=str(e))
            return []
        logger.debug("fanart_tv_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: TheTVDB v4 (key-gated, cached bearer token)
    # ------------------------------------------------------------------

    async def _thetvdb_token(self, api_key: str) -> Optional[str]:
        """Login to TheTVDB v4; cache bearer token for 1h."""
        now = time.time()
        token = _THETVDB_TOKEN.get("token")
        exp = _THETVDB_TOKEN.get("expires_at", 0.0)
        if token and now < exp:
            return token
        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    "https://api4.thetvdb.com/v4/login",
                    json={"apikey": api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    tok = (data.get("data") or {}).get("token")
                    if tok:
                        _THETVDB_TOKEN["token"] = tok
                        _THETVDB_TOKEN["expires_at"] = now + 3600
                        return tok
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("thetvdb_login_failed", error=str(e))
        return None

    async def source_thetvdb_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """TheTVDB v4 series image search."""
        settings = get_settings()
        if not settings.thetvdb_api_key:
            return []
        token = await self._thetvdb_token(settings.thetvdb_api_key)
        if not token:
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://api4.thetvdb.com/v4/search",
                    params={"query": name, "type": "series"},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for entry in data.get("data", []) or []:
                        for key in ("image_url", "thumbnail"):
                            u = entry.get(key)
                            if u and isinstance(u, str) and u.startswith("http"):
                                images.append({
                                    "url": u,
                                    "source": "thetvdb",
                                    "query_used": f"thetvdb:{name}",
                                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("thetvdb_failed", name=name, error=str(e))
            return []
        logger.debug("thetvdb_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Giant Bomb (key-gated)
    # ------------------------------------------------------------------

    async def source_giant_bomb_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Giant Bomb character search (key-gated)."""
        settings = get_settings()
        if not settings.giant_bomb_api_key:
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://www.giantbomb.com/api/search/",
                    params={
                        "api_key": settings.giant_bomb_api_key,
                        "format": "json",
                        "resources": "character",
                        "query": name,
                        "limit": 5,
                        "field_list": "name,image",
                    },
                    headers={"User-Agent": "Zero/1.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for r in data.get("results", []) or []:
                        img = r.get("image") or {}
                        u = img.get("super_url")
                        if u and isinstance(u, str) and u.startswith("http"):
                            images.append({
                                "url": u,
                                "source": "giant_bomb",
                                "query_used": f"giant_bomb:{name}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("giant_bomb_failed", name=name, error=str(e))
            return []
        logger.debug("giant_bomb_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: Jikan v4 (no key, anime-gated)
    # ------------------------------------------------------------------

    async def source_jikan_anime_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Jikan v4 anime character images (no key; universe/franchise gated)."""
        u_lc = (universe or "").lower()
        f_lc = (franchise or "").lower()
        anime_hints = (
            "anime", "manga", "naruto", "one_piece", "one piece",
            "dragonball", "dragon ball", "bleach", "jujutsu",
            "demon_slayer", "demon slayer", "attack_on_titan",
            "attack on titan", "my_hero", "my hero", "pokemon",
        )
        if not (
            "anime" in u_lc or "manga" in u_lc
            or any(h in u_lc or h in f_lc for h in anime_hints)
        ):
            return []
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://api.jikan.moe/v4/characters",
                    params={"q": name, "limit": 5},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for entry in data.get("data", []) or []:
                        imgs = entry.get("images") or {}
                        jpg = (imgs.get("jpg") or {}).get("image_url")
                        webp = (imgs.get("webp") or {}).get("large_image_url")
                        for u in (jpg, webp):
                            if u and isinstance(u, str) and u.startswith("http"):
                                images.append({
                                    "url": u,
                                    "source": "jikan",
                                    "query_used": f"jikan:{name}",
                                })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("jikan_failed", name=name, error=str(e))
            return []
        logger.debug("jikan_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: SuperHero API (key-gated, marvel/dc-gated)
    # ------------------------------------------------------------------

    async def source_superhero_api_images(
        self, name: str, universe: str, franchise: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """SuperHero API character images (key-gated, marvel/dc-gated)."""
        settings = get_settings()
        if not settings.superhero_api_key:
            return []
        u_lc = (universe or "").lower()
        f_lc = (franchise or "").lower()
        hero_hints = (
            "marvel", "dc", "avengers", "x-men", "xmen",
            "justice league", "justice_league",
            "batman", "superman", "spider", "wonder woman",
        )
        if not (
            u_lc in ("marvel", "dc")
            or any(h in u_lc or h in f_lc for h in hero_hints)
        ):
            return []
        images: List[Dict[str, Any]] = []
        try:
            from urllib.parse import quote
            url = (
                f"https://superheroapi.com/api/{settings.superhero_api_key}"
                f"/search/{quote(name)}"
            )
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    url, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for r in data.get("results", []) or []:
                        img = (r.get("image") or {}).get("url")
                        if img and isinstance(img, str) and img.startswith("http"):
                            images.append({
                                "url": img,
                                "source": "superhero_api",
                                "query_used": f"superhero_api:{name}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError) as e:
            logger.warning("superhero_api_failed", name=name, error=str(e))
            return []
        logger.debug("superhero_api_images", name=name, count=len(images))
        return images

    # ------------------------------------------------------------------
    # Source: DeviantArt (OAuth required; stubbed)
    # ------------------------------------------------------------------

    async def source_deviantart_images(
        self, name: str,
    ) -> List[Dict[str, Any]]:
        """DeviantArt requires OAuth; stub until creds are wired."""
        settings = get_settings()
        if not (settings.deviantart_client_id and settings.deviantart_client_secret):
            logger.debug("deviantart_skipped", name=name, reason="no_oauth")
            return []
        # Placeholder: OAuth client credentials flow would be implemented here.
        logger.debug("deviantart_skipped", name=name, reason="oauth_flow_not_implemented")
        return []

    # ------------------------------------------------------------------
    # Source: ArtStation (public search, no key)
    # ------------------------------------------------------------------

    async def source_artstation_images(
        self, name: str,
    ) -> List[Dict[str, Any]]:
        """Search ArtStation public API for project cover images."""
        images: List[Dict[str, Any]] = []
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(
                    "https://www.artstation.com/api/v2/search/projects.json",
                    params={
                        "query": name,
                        "page": 1,
                        "per_page": 10,
                    },
                    headers={"User-Agent": "ZeroBot/1.0 (image research)"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    for item in data.get("data", []) or []:
                        cover = item.get("cover_url") or item.get("cover", {}).get("url")
                        if cover and isinstance(cover, str) and cover.startswith("http"):
                            images.append({
                                "url": cover,
                                "source": "artstation",
                                "query_used": f"artstation:{name}",
                            })
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
                OSError, KeyError, TypeError):
            return []
        logger.debug("artstation_images", name=name, count=len(images))
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
            img.load()
            result["width"] = img.width
            result["height"] = img.height
            result["is_valid"] = img.width >= 800
            # Compute perceptual hash for near-dupe detection.
            try:
                import imagehash  # type: ignore
                result["phash"] = str(imagehash.phash(img.convert("RGB")))
            except ImportError:
                result["phash"] = None
            except (ValueError, OSError):
                result["phash"] = None
            # sha256 over the fetched prefix (first 64KB). Not full-body, but good
            # enough to catch CDN-served byte-identical duplicates we see in
            # practice (e.g. same Fandom image reappearing under multiple URLs).
            # Full-body hashing is deferred until MinIO is in the loop.
            try:
                import hashlib as _hashlib
                result["sha256"] = _hashlib.sha256(chunk).hexdigest()
            except Exception:  # noqa: BLE001
                result["sha256"] = None
            # Compute lightweight quality signals (face + safe zone).
            try:
                signals = _compute_quality_signals(img)
                result["face_present"] = signals.get("face_present", False)
                result["safe_zone_score"] = signals.get("safe_zone_score", 0.0)
                result["centered_score"] = signals.get("centered_score", 0.0)
            except (ValueError, OSError, ImportError):
                pass
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            pass
        return result


@lru_cache()
def get_image_source_service() -> ImageSourceService:
    return ImageSourceService()
