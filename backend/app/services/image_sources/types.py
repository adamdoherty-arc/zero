"""Shared types for image source plugins."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ImageQuery(BaseModel):
    """A request the fan-out fetcher hands to every plugin."""

    character: str
    franchise: Optional[str] = None
    actor: Optional[str] = None
    title_id: Optional[str] = None  # TMDB / IMDb id when known
    aliases: list[str] = Field(default_factory=list)
    angle_keywords: list[str] = Field(default_factory=list)


class CandidateImage(BaseModel):
    """A single image candidate emitted by a source plugin.

    The scorer enriches this with CV signals (blur, aspect), CLIP relevance,
    aesthetic, face cosine, watermark flag, VLM verdict, and a composite
    z-score.
    """

    source: str  # tmdb | fanart | comic_vine | wikimedia | reddit_praw | imdb | pexels | unsplash
    source_url: str
    width: Optional[int] = None
    height: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    license: Optional[str] = None
    attribution: Optional[str] = None
    raw_metadata: dict = Field(default_factory=dict)
