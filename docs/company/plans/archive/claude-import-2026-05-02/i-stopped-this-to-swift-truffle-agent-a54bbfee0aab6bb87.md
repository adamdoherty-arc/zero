# Plan: Add 6 Niche Image Sources to Character Content Pipeline

## Scope
Add 6 new image sources to `backend/app/services/image_source_service.py` (ComicVine, Fanart.tv, TheTVDB, Giant Bomb, Jikan, SuperHero API), wire new settings keys in `backend/app/infrastructure/config.py`, update SOURCE_TIERS, and wire tasks into `discover_images()`.

## Files Changed
1. `c:\code\zero\backend\app\infrastructure\config.py` — add 5 Optional[str] settings
2. `c:\code\zero\backend\app\services\image_source_service.py` — tiers, 6 methods, wiring

---

## Change 1: config.py — 5 new Optional[str] settings

Insert after line 109 (`omdb_api_key`), in the "Additional image sources" block:

```python
    # Niche character image APIs
    comicvine_api_key: Optional[str] = None
    fanart_api_key: Optional[str] = None
    thetvdb_api_key: Optional[str] = None
    giant_bomb_api_key: Optional[str] = None
    superhero_api_key: Optional[str] = None
```

---

## Change 2: image_source_service.py — SOURCE_TIERS entries

Add to `SOURCE_TIERS` dict (around line 36–58):

```python
    "comicvine": 0.85,
    "fanart_tv": 0.85,
    "thetvdb": 0.8,
    "giant_bomb": 0.8,
    "jikan": 0.8,
    "superhero_api": 0.75,
```

---

## Change 3: image_source_service.py — module-level TheTVDB token cache

Add near top (after `TMDB_IMAGE_BASE`, line 61):

```python
# TheTVDB bearer token cache (1h expiry)
_THETVDB_TOKEN: Dict[str, Any] = {"token": None, "expires_at": 0.0}
```

Also add `import time` at the top of the file.

---

## Change 4: image_source_service.py — 6 new source methods

Insert before the DeviantArt section (line 1152). All follow the existing style:
- `async`, `aiohttp.ClientSession`, `ClientTimeout(total=10)`
- Return list of `{url, source, query_used}` dicts
- Catch `(aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError, KeyError, TypeError)` → `[]`
- `logger.warning(...)` on failure, `logger.debug(...)` on completion

### 4a. ComicVine

```python
async def source_comicvine_images(
    self, name: str, universe: str, franchise: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """ComicVine character image search (key-gated)."""
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
```

### 4b. Fanart.tv (TMDB-ID-dependent)

```python
async def source_fanart_tv_images(
    self, name: str, universe: str, franchise: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fanart.tv images, keyed off TMDB ID discovered via TMDB search."""
    settings = get_settings()
    if not settings.fanart_api_key:
        return []
    access_token = settings.tmdp_read_access_token
    api_key = settings.tmdp_api_key
    if not access_token and not api_key:
        return []

    images: List[Dict[str, Any]] = []
    try:
        # Step 1: find TMDB ID via multi-search
        tmdb_headers = (
            {"Authorization": f"Bearer {access_token}"} if access_token else {}
        )
        tmdb_params = {
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
            if not tmdb_id:
                return []

            # Step 2: query fanart.tv with TMDB ID
            url = f"https://webservice.fanart.tv/v3/{media_type}/{tmdb_id}"
            async with http.get(
                url, params={"api_key": settings.fanart_api_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                for key in ("hdmovielogo", "moviebackground", "movieposter",
                            "hdtvlogo", "showbackground", "tvposter"):
                    for entry in data.get(key, []) or []:
                        u = entry.get("url")
                        if u and isinstance(u, str) and u.startswith("http"):
                            images.append({
                                "url": u,
                                "source": "fanart_tv",
                                "query_used": f"fanart_tv:{media_type}/{tmdb_id}",
                            })
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError,
            OSError, KeyError, TypeError) as e:
        logger.warning("fanart_tv_failed", name=name, error=str(e))
        return []
    logger.debug("fanart_tv_images", name=name, count=len(images))
    return images
```

### 4c. TheTVDB (login + token cache)

```python
async def _thetvdb_token(self, api_key: str) -> Optional[str]:
    """Login to TheTVDB v4 and cache the bearer token for 1h."""
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
    """TheTVDB v4 series image search (key-gated, cached bearer token)."""
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
```

### 4d. Giant Bomb

```python
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
```

### 4e. Jikan (anime-gated, no key)

```python
async def source_jikan_anime_images(
    self, name: str, universe: str, franchise: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Jikan v4 anime character images (no key; universe-gated to anime)."""
    u_lc = (universe or "").lower()
    f_lc = (franchise or "").lower()
    anime_hints = ("anime", "manga", "naruto", "one_piece", "dragonball",
                    "bleach", "jujutsu", "demon_slayer", "attack_on_titan",
                    "my_hero", "pokemon")
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
```

### 4f. SuperHero API (marvel/dc-gated)

```python
async def source_superhero_api_images(
    self, name: str, universe: str, franchise: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """SuperHero API (key-gated, marvel/dc-gated)."""
    settings = get_settings()
    if not settings.superhero_api_key:
        return []
    u_lc = (universe or "").lower()
    f_lc = (franchise or "").lower()
    hero_hints = ("marvel", "dc", "avengers", "x-men", "justice league",
                    "batman", "superman", "spider")
    if not (u_lc in ("marvel", "dc")
            or any(h in u_lc or h in f_lc for h in hero_hints)):
        return []
    images: List[Dict[str, Any]] = []
    try:
        # URL-encode the name segment
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
```

---

## Change 5: Wiring into `discover_images()`

Append to the settings-based conditional block (after the `omdb_api_key` block, around line 255):

```python
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
# Jikan — no key, but universe-gated (method self-gates on anime hints)
tasks.append(self._safe_source(
    self.source_jikan_anime_images, name, universe, franchise,
))
if settings.superhero_api_key:
    tasks.append(self._safe_source(
        self.source_superhero_api_images, name, universe, franchise,
    ))
```

---

## Verification Steps (post-execute)

1. Syntax check:
   ```bash
   python -c "import ast; ast.parse(open('backend/app/services/image_source_service.py').read())"
   python -c "import ast; ast.parse(open('backend/app/infrastructure/config.py').read())"
   ```
2. Rebuild backend per CLAUDE.md mandate:
   ```bash
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api \
     && docker compose -f docker-compose.sprint.yml up -d zero-api
   ```
3. Verify container healthy: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero-api`
4. Verify no import error: `docker logs zero-api --tail 50 | grep -i error`

## Non-Breaking Guarantees
- All 5 new settings default to `None` (identical shape to existing `omdb_api_key`, `giphy_api_key`, etc.)
- All 5 key-gated methods early-return `[]` when the key is absent
- Jikan is the only always-wired task; its self-gating on anime hints ensures it returns `[]` for non-anime universes before making any HTTP call
- SOURCE_TIERS additions only expand the dict; existing lookups via `.get(source, 0.5)` unchanged
- No existing method signatures touched
