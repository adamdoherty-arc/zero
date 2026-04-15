"""
Music Library Service.

Manages music tracks for character carousels.
Provides mood matching, trending sound discovery, and auto-assignment.
"""

import asyncio
import secrets
from functools import lru_cache
from typing import List, Optional, Dict, Any

import aiohttp
import structlog
from sqlalchemy import select, update

from app.db.models import MusicTrackModel
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_session
from app.models.character_content import MusicTrack, MusicTrackCreate

logger = structlog.get_logger()


# Mood keywords for matching carousel content to music
MOOD_KEYWORDS = {
    "epic": ["powerful", "hero", "battle", "vs", "strongest", "greatest", "ultimate", "legendary"],
    "dark": ["dark", "evil", "villain", "death", "tragedy", "suffering", "cruel", "nightmare"],
    "emotional": ["love", "loss", "sacrifice", "heart", "family", "farewell", "crying", "pain"],
    "mysterious": ["secret", "hidden", "unknown", "theory", "mystery", "conspiracy", "truth"],
    "dramatic": ["reveal", "changed", "everything", "shocking", "twist", "surprise", "plot"],
    "hype": ["insane", "crazy", "goat", "fire", "legendary", "best", "top", "unreal"],
    "chill": ["underrated", "peaceful", "quiet", "gentle", "calm", "wise"],
}

# Angle to mood mapping
ANGLE_MOOD_MAP = {
    "hidden_truths": "mysterious",
    "power_secrets": "epic",
    "underrated_moments": "emotional",
    "origin_story": "dramatic",
    "character_evolution": "emotional",
    "controversial_takes": "dramatic",
    "vs_comparison": "epic",
    "behind_scenes": "chill",
    "fan_theories": "mysterious",
    "dark_facts": "dark",
    "actor_secrets": "dramatic",
    "easter_eggs": "mysterious",
    "crossover_connections": "mysterious",
    "what_if": "dramatic",
    "timeline_deep_dive": "emotional",
}


# Pre-built music library (50 tracks)
SEED_TRACKS = [
    # Epic
    {"name": "Time", "artist": "Hans Zimmer", "mood": "epic", "energy_level": "high", "genre": "cinematic"},
    {"name": "Heart of Courage", "artist": "Two Steps from Hell", "mood": "epic", "energy_level": "high", "genre": "trailer"},
    {"name": "Victory", "artist": "Two Steps from Hell", "mood": "epic", "energy_level": "high", "genre": "trailer"},
    {"name": "Portals", "artist": "Alan Silvestri", "mood": "epic", "energy_level": "high", "genre": "cinematic"},
    {"name": "He's a Pirate", "artist": "Hans Zimmer", "mood": "epic", "energy_level": "high", "genre": "cinematic"},
    {"name": "Duel of the Fates", "artist": "John Williams", "mood": "epic", "energy_level": "high", "genre": "cinematic"},
    {"name": "The Avengers Theme", "artist": "Alan Silvestri", "mood": "epic", "energy_level": "high", "genre": "cinematic"},
    # Dark
    {"name": "Why So Serious", "artist": "Hans Zimmer", "mood": "dark", "energy_level": "medium", "genre": "cinematic"},
    {"name": "Lacrimosa", "artist": "Mozart", "mood": "dark", "energy_level": "medium", "genre": "classical"},
    {"name": "Imperial March", "artist": "John Williams", "mood": "dark", "energy_level": "medium", "genre": "cinematic"},
    {"name": "O Fortuna", "artist": "Carl Orff", "mood": "dark", "energy_level": "high", "genre": "classical"},
    {"name": "Requiem for a Dream", "artist": "Clint Mansell", "mood": "dark", "energy_level": "high", "genre": "cinematic"},
    {"name": "Come Sweet Death", "artist": "Bach", "mood": "dark", "energy_level": "low", "genre": "classical"},
    {"name": "Venom Theme", "artist": "Ludwig Goransson", "mood": "dark", "energy_level": "medium", "genre": "cinematic"},
    # Emotional
    {"name": "Married Life", "artist": "Michael Giacchino", "mood": "emotional", "energy_level": "low", "genre": "cinematic"},
    {"name": "Interstellar Main Theme", "artist": "Hans Zimmer", "mood": "emotional", "energy_level": "medium", "genre": "cinematic"},
    {"name": "Hedwig's Theme", "artist": "John Williams", "mood": "emotional", "energy_level": "low", "genre": "cinematic"},
    {"name": "Concerning Hobbits", "artist": "Howard Shore", "mood": "emotional", "energy_level": "low", "genre": "cinematic"},
    {"name": "See You Again", "artist": "Wiz Khalifa", "mood": "emotional", "energy_level": "medium", "genre": "pop"},
    {"name": "My Heart Will Go On", "artist": "Celine Dion", "mood": "emotional", "energy_level": "medium", "genre": "pop"},
    {"name": "Leaves from the Vine", "artist": "Avatar TLA", "mood": "emotional", "energy_level": "low", "genre": "animated"},
    # Mysterious
    {"name": "Stranger Things Theme", "artist": "Kyle Dixon", "mood": "mysterious", "energy_level": "low", "genre": "synth"},
    {"name": "Doctor Strange Theme", "artist": "Michael Giacchino", "mood": "mysterious", "energy_level": "medium", "genre": "cinematic"},
    {"name": "X-Files Theme", "artist": "Mark Snow", "mood": "mysterious", "energy_level": "low", "genre": "tv"},
    {"name": "Westworld Theme", "artist": "Ramin Djawadi", "mood": "mysterious", "energy_level": "medium", "genre": "cinematic"},
    {"name": "Inception Main Theme", "artist": "Hans Zimmer", "mood": "mysterious", "energy_level": "medium", "genre": "cinematic"},
    {"name": "Twin Peaks Theme", "artist": "Angelo Badalamenti", "mood": "mysterious", "energy_level": "low", "genre": "tv"},
    {"name": "Moon Knight Theme", "artist": "Hesham Nazih", "mood": "mysterious", "energy_level": "medium", "genre": "cinematic"},
    # Dramatic
    {"name": "Cornfield Chase", "artist": "Hans Zimmer", "mood": "dramatic", "energy_level": "high", "genre": "cinematic"},
    {"name": "The Dark Knight Theme", "artist": "Hans Zimmer", "mood": "dramatic", "energy_level": "high", "genre": "cinematic"},
    {"name": "Battle of the Heroes", "artist": "John Williams", "mood": "dramatic", "energy_level": "high", "genre": "cinematic"},
    {"name": "No Time to Die", "artist": "Billie Eilish", "mood": "dramatic", "energy_level": "medium", "genre": "pop"},
    {"name": "Immigrant Song", "artist": "Led Zeppelin", "mood": "dramatic", "energy_level": "high", "genre": "rock"},
    {"name": "Game of Thrones Theme", "artist": "Ramin Djawadi", "mood": "dramatic", "energy_level": "medium", "genre": "cinematic"},
    {"name": "Logan Theme", "artist": "Marco Beltrami", "mood": "dramatic", "energy_level": "medium", "genre": "cinematic"},
    # Hype
    {"name": "Blinding Lights", "artist": "The Weeknd", "mood": "hype", "energy_level": "high", "genre": "pop"},
    {"name": "Unstoppable", "artist": "Sia", "mood": "hype", "energy_level": "high", "genre": "pop"},
    {"name": "Industry Baby", "artist": "Lil Nas X", "mood": "hype", "energy_level": "high", "genre": "hip-hop"},
    {"name": "Believer", "artist": "Imagine Dragons", "mood": "hype", "energy_level": "high", "genre": "rock"},
    {"name": "Whatever It Takes", "artist": "Imagine Dragons", "mood": "hype", "energy_level": "high", "genre": "rock"},
    {"name": "Legends Never Die", "artist": "League of Legends", "mood": "hype", "energy_level": "high", "genre": "gaming"},
    {"name": "Enemy", "artist": "Imagine Dragons", "mood": "hype", "energy_level": "high", "genre": "rock"},
    # Chill
    {"name": "Lo-Fi Study Beats", "artist": "Various", "mood": "chill", "energy_level": "low", "genre": "lo-fi"},
    {"name": "Experience", "artist": "Ludovico Einaudi", "mood": "chill", "energy_level": "low", "genre": "classical"},
    {"name": "Weightless", "artist": "Marconi Union", "mood": "chill", "energy_level": "low", "genre": "ambient"},
    {"name": "Clair de Lune", "artist": "Debussy", "mood": "chill", "energy_level": "low", "genre": "classical"},
    {"name": "Gymnop\u00e9die No.1", "artist": "Erik Satie", "mood": "chill", "energy_level": "low", "genre": "classical"},
    {"name": "River Flows in You", "artist": "Yiruma", "mood": "chill", "energy_level": "low", "genre": "classical"},
    {"name": "Divenire", "artist": "Ludovico Einaudi", "mood": "chill", "energy_level": "low", "genre": "classical"},
]


class MusicLibraryService:
    """Manages music tracks for character carousels."""

    def __init__(self):
        settings = get_settings()
        self._searxng_url = settings.searxng_url
        self._timeout = aiohttp.ClientTimeout(total=15)

    async def seed_music_library(self) -> List[MusicTrack]:
        """Pre-populate the music library with curated tracks."""
        seeded = []
        async with get_session() as session:
            for track_data in SEED_TRACKS:
                # Check if already exists
                result = await session.execute(
                    select(MusicTrackModel).where(
                        MusicTrackModel.name == track_data["name"],
                        MusicTrackModel.artist == track_data.get("artist"),
                    )
                )
                if result.scalar_one_or_none():
                    continue

                row = MusicTrackModel(
                    id=f"mt-{secrets.token_hex(12)}",
                    name=track_data["name"],
                    artist=track_data.get("artist"),
                    mood=track_data["mood"],
                    energy_level=track_data.get("energy_level", "medium"),
                    genre=track_data.get("genre"),
                    tags=[track_data["mood"], track_data.get("genre", "")],
                )
                session.add(row)
                seeded.append(self._row_to_model(row))

        logger.info("music_library_seeded", count=len(seeded))
        return seeded

    async def recommend_music(
        self, carousel_text: str, angle: Optional[str] = None, mood_override: Optional[str] = None
    ) -> List[MusicTrack]:
        """Recommend music tracks for a carousel based on content analysis."""
        # Determine mood from angle or content keywords
        if mood_override:
            target_mood = mood_override
        elif angle and angle in ANGLE_MOOD_MAP:
            target_mood = ANGLE_MOOD_MAP[angle]
        else:
            target_mood = self._detect_mood(carousel_text)

        # Get tracks matching the mood
        async with get_session() as session:
            result = await session.execute(
                select(MusicTrackModel)
                .where(MusicTrackModel.mood == target_mood)
                .order_by(MusicTrackModel.trending_score.desc(), MusicTrackModel.use_count.asc())
                .limit(3)
            )
            rows = result.scalars().all()

        if not rows:
            # Fallback: get any tracks
            async with get_session() as session:
                result = await session.execute(
                    select(MusicTrackModel).order_by(MusicTrackModel.use_count.asc()).limit(3)
                )
                rows = result.scalars().all()

        return [self._row_to_model(r) for r in rows]

    async def get_tracks(
        self, mood: Optional[str] = None, limit: int = 50
    ) -> List[MusicTrack]:
        """List tracks, optionally filtered by mood."""
        async with get_session() as session:
            q = select(MusicTrackModel).order_by(
                MusicTrackModel.trending_score.desc()
            ).limit(limit)
            if mood:
                q = q.where(MusicTrackModel.mood == mood)
            result = await session.execute(q)
            rows = result.scalars().all()
        return [self._row_to_model(r) for r in rows]

    async def add_track(self, data: MusicTrackCreate) -> MusicTrack:
        """Add a track to the library."""
        row = MusicTrackModel(
            id=f"mt-{secrets.token_hex(12)}",
            name=data.name,
            artist=data.artist,
            mood=data.mood,
            energy_level=data.energy_level,
            genre=data.genre,
            tiktok_sound_id=data.tiktok_sound_id,
            tiktok_sound_url=data.tiktok_sound_url,
            tags=data.tags or [data.mood],
        )
        async with get_session() as session:
            session.add(row)
            await session.flush()
        return self._row_to_model(row)

    async def search_trending_sounds(self, niche: str = "character facts") -> List[Dict[str, Any]]:
        """Search for trending TikTok sounds via SearXNG."""
        queries = [
            f"trending tiktok sounds {niche} 2026",
            f"viral tiktok audio {niche} carousel",
        ]
        results = []
        async with aiohttp.ClientSession(timeout=self._timeout) as session:
            for query in queries:
                try:
                    params = {"q": query, "format": "json", "engines": "google"}
                    async with session.get(
                        f"{self._searxng_url}/search", params=params
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                    for r in data.get("results", [])[:5]:
                        results.append({
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "snippet": r.get("content", ""),
                        })
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, ConnectionError) as e:
                    logger.debug("trending_search_error", error=str(e))

        return results

    async def increment_usage(self, track_id: str) -> None:
        """Increment usage counter when a track is assigned to a carousel."""
        async with get_session() as session:
            await session.execute(
                update(MusicTrackModel)
                .where(MusicTrackModel.id == track_id)
                .values(use_count=MusicTrackModel.use_count + 1)
            )

    async def assign_track_to_carousel(self, carousel_id: str, track_id: str) -> Dict[str, Any]:
        """Assign a music track to a carousel."""
        from app.db.models import CharacterCarouselModel
        async with get_session() as session:
            result = await session.execute(
                select(MusicTrackModel).where(MusicTrackModel.id == track_id)
            )
            track = result.scalar_one_or_none()
            if not track:
                raise ValueError(f"Track {track_id} not found")

            track_data = {
                "id": track.id, "name": track.name, "artist": track.artist,
                "mood": track.mood, "genre": track.genre,
            }
            await session.execute(
                update(CharacterCarouselModel)
                .where(CharacterCarouselModel.id == carousel_id)
                .values(music_track=track_data, music_mood=track.mood)
            )
            track.use_count += 1

        return {"carousel_id": carousel_id, "track": track_data}

    def _detect_mood(self, text: str) -> str:
        """Simple keyword-based mood detection from carousel text."""
        text_lower = text.lower()
        scores = {}
        for mood, keywords in MOOD_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            scores[mood] = score

        if not scores or max(scores.values()) == 0:
            return "dramatic"  # Safe default

        return max(scores, key=scores.get)

    def _row_to_model(self, row: MusicTrackModel) -> MusicTrack:
        """Convert ORM row to Pydantic model."""
        return MusicTrack(
            id=row.id,
            name=row.name,
            artist=row.artist,
            mood=row.mood,
            energy_level=row.energy_level,
            genre=row.genre,
            tiktok_sound_id=row.tiktok_sound_id,
            tiktok_sound_url=row.tiktok_sound_url,
            is_trending=row.is_trending if row.is_trending is not None else False,
            trending_score=row.trending_score or 0.0,
            use_count=row.use_count or 0,
            avg_engagement=row.avg_engagement or 0.0,
            tags=row.tags or [],
            metadata=row.metadata_ or {},
            created_at=row.created_at,
        )


@lru_cache()
def get_music_library_service() -> MusicLibraryService:
    """Get cached music library service instance."""
    return MusicLibraryService()
