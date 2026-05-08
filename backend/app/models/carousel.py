"""Carousel V2 Pydantic models — the canonical shapes that flow through the
Temporal workflow defined in ``app.workflows.carousel_workflow``.

These complement ``app.models.character_content`` rather than replace it. The
V1 monolithic ``CarouselCreate`` / ``CarouselSlide`` shapes keep flowing through
the legacy pipeline (``CharacterContentService.generate_carousel``) until the
Phase 6 cutover. V2 lives next to them and is what ``CarouselGenerationModel``
serialises into JSONB columns.

Design notes (from carosel.txt blueprint):

- Every claim ends with ``[fact_id:N]`` — citation-grounded generation. The
  ``Slide.text`` field is post-processed by a regex that strips uncited
  sentences before render.

- Every image carries a ``composite_z`` from the 11-stage funnel and the raw
  signals (CLIP, aesthetic, face cosine, VLM verdict). Never trust a single
  signal — always rank by composite.

- ``CarouselRubric`` is 7 axes, each 1-5 Likert per Prometheus-Vision pattern.
  The composite is a weighted sum; threshold 7.5/10 gates auto-publish.

- ``Skeptic`` returns one of KEEP/REWRITE/KILL per atomic claim with a
  ``trap_category`` from a fixed enum.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Source ledger
# ---------------------------------------------------------------------------

class TrustTier(int, Enum):
    """Source trust tier (carosel.txt §3 'Tiered source ledger')."""
    CANON = 1            # Fandom MediaWiki, TMDB, TVDB, Wikipedia, Wikidata, Comic Vine
    SEMI_STRUCTURED = 2  # IMDb GraphQL trivia, Box Office Mojo, MCU Exchange
    COMMUNITY = 3        # Reddit, TikTok Creative Center, YouTube transcripts
    NEWS = 4             # Variety, THR, CBR, Screen Rant — cross-confirm required


class SourceKind(str, Enum):
    FANDOM = "fandom"
    TMDB = "tmdb"
    TVDB = "tvdb"
    WIKIPEDIA = "wikipedia"
    WIKIDATA = "wikidata"
    COMIC_VINE = "comic_vine"
    IMDB_GRAPHQL = "imdb_graphql"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    NEWS = "news"
    OTHER = "other"


class Source(BaseModel):
    """Pointer to the upstream artifact that backs an atomic fact."""
    kind: SourceKind
    url: str
    quote: Optional[str] = None
    fetched_at: Optional[datetime] = None
    revision_id: Optional[str] = None


class AtomicFact(BaseModel):
    """The unit of grounding. Every published claim cites one of these by id.

    Cross-source rule: every published fact requires ≥2 Tier-1/2 sources OR a
    single Tier-1 (carosel.txt §3 'Hallucination prevention').
    """
    id: str
    subject: str
    predicate: str
    object: str
    trust_tier: TrustTier
    source: Source
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    franchise: Optional[str] = None
    sha256: str
    supersedes_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Image curation
# ---------------------------------------------------------------------------

class ImageSourceKind(str, Enum):
    TMDB = "tmdb"
    FANART = "fanart"
    COMIC_VINE = "comic_vine"
    WIKIMEDIA = "wikimedia"
    REDDIT_PRAW = "reddit_praw"
    IMDB = "imdb"
    PEXELS = "pexels"
    UNSPLASH = "unsplash"
    BING_CSE = "bing_cse"
    GOOGLE_CSE = "google_cse"


class ImageScore(BaseModel):
    """11-stage funnel audit trail per candidate image (carosel.txt §1).

    The funnel is strictly cost-ascending — every stage is more expensive than
    the last, so we prune cheaply first. Composite z-score combines all signals
    with calibrated weights.
    """
    id: str
    source: ImageSourceKind
    source_url: str
    phash: Optional[str] = None
    dhash: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # Stage 1 cheap CV
    blur_variance: Optional[float] = None
    nsfw_score: Optional[float] = None
    aspect_match: Optional[bool] = None

    # Stage 3 CLIP relevance
    clip_relevance: Optional[float] = None
    clip_alt_softmax: dict[str, float] = Field(default_factory=dict)

    # Stage 4 aesthetic + IQA
    aesthetic_v2: Optional[float] = None
    maniqa: Optional[float] = None
    clip_iqa: Optional[float] = None

    # Stage 5 face verification
    face_cosine: Optional[float] = None
    face_actor: Optional[str] = None

    # Stage 6 watermark / overlay
    watermark_flag: bool = False
    text_overlay_flag: bool = False

    # Stage 8 VLM final verifier
    vlm_likeness: Optional[float] = None
    vlm_is_promotional_still: Optional[bool] = None
    vlm_response: dict[str, Any] = Field(default_factory=dict)
    vlm_model: Optional[str] = None
    # Carousel V2 cheap-VLM router stamps these so cost telemetry can attribute
    # spend back to the tier (kimi | openrouter_free | gemini_paid).
    vlm_tier: Optional[str] = None
    vlm_cost_usd: Optional[float] = None

    # Stage 9 composite
    composite_z: Optional[float] = None
    rank: Optional[int] = None
    kept: bool = False
    drop_reason: Optional[str] = None

    # Stage 10/11 outputs
    upscaled_url: Optional[str] = None
    crop_box: Optional[dict[str, int]] = None


# ---------------------------------------------------------------------------
# Slide + carousel
# ---------------------------------------------------------------------------

class SlideRole(str, Enum):
    """Carousel arc structure (carosel.txt §3 'Carousel arc')."""
    HOOK = "hook"
    SETUP = "setup"
    BUILD = "build"
    PIVOT = "pivot"
    REVEAL = "reveal"
    PAYOFF = "payoff"
    CONNECTION = "connection"
    CTA = "cta"


class SkepticVerdict(str, Enum):
    KEEP = "keep"
    REWRITE = "rewrite"
    KILL = "kill"


class TrapCategory(str, Enum):
    """Known hallucination trap categories for character/franchise content."""
    ACTOR_SWAP = "actor_swap"
    MOVIE_MISATTRIBUTION = "movie_misattribution"
    COMIC_VS_SCREEN = "comic_vs_screen"
    FAN_THEORY = "fan_theory"
    RETCON = "retcon"
    MADE_UP_EASTER_EGG = "made_up_easter_egg"


class SkepticReport(BaseModel):
    """Output of the Skeptic agent for a single atomic claim."""
    claim: str
    supporting_quote: Optional[str] = None
    trap_category: Optional[TrapCategory] = None
    verdict: SkepticVerdict
    rewrite_suggestion: Optional[str] = None


class Slide(BaseModel):
    """A single carousel slide. ``text`` ends with ``[fact_id:N]`` citations,
    one per claim. ``image`` is selected from the 11-stage funnel.
    """
    slide_num: int
    role: SlideRole
    text: str
    transition_to_next: Optional[str] = None
    image: Optional[ImageScore] = None
    cited_fact_ids: list[str] = Field(default_factory=list)
    template: str = "fact"  # one of: hook|fact|fact_overlay|comparison|quote|reveal_blur|easter_egg|tier|cta
    skeptic_reports: list[SkepticReport] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rubric — 7 axes, Bradley-Terry weighted across 3 judges
# ---------------------------------------------------------------------------

class RubricAxis(str, Enum):
    HOOK_STRENGTH = "hook_strength"
    FACT_ACCURACY = "fact_accuracy"
    IMAGE_RELEVANCE = "image_relevance"
    NARRATIVE_ARC = "narrative_arc"
    DESIGN_POLISH = "design_polish"
    VOICE_CONSISTENCY = "voice_consistency"
    NOVELTY = "novelty"


# Composite weights from carosel.txt §5. Weights sum to 1.0 across the seven
# axes; the composite is in [0, 10].
RUBRIC_WEIGHTS: dict[RubricAxis, float] = {
    RubricAxis.HOOK_STRENGTH: 0.30,
    RubricAxis.FACT_ACCURACY: 0.25,
    RubricAxis.NARRATIVE_ARC: 0.20,
    RubricAxis.IMAGE_RELEVANCE: 0.15,
    RubricAxis.DESIGN_POLISH: 0.10,
    # Voice and novelty are reported per-axis but not in the weighted composite —
    # they gate auto-publish independently (voice <6 or novelty <4 → escalate).
    RubricAxis.VOICE_CONSISTENCY: 0.0,
    RubricAxis.NOVELTY: 0.0,
}


# Auto-publish floor (carosel.txt §4). Below this, route to reflexion or HITL.
AUTO_PUBLISH_THRESHOLD = 7.5
AUTO_PUBLISH_VOICE_FLOOR = 6.0
AUTO_PUBLISH_NOVELTY_FLOOR = 4.0


class JudgeName(str, Enum):
    KIMI_K2_6 = "kimi_k2_6"
    MINIMAX_M2_7 = "minimax_m2_7"
    QWEN3_32B_LOCAL = "qwen3_32b_local"


class JudgeAxisScore(BaseModel):
    judge: JudgeName
    axis: RubricAxis
    score: float = Field(ge=0.0, le=10.0)
    rationale: Optional[str] = None
    samples_n: int = 1
    trust_weight: float = 1.0


class CarouselRubric(BaseModel):
    """7-axis rubric with 3-judge Bradley-Terry weighted aggregation.

    Self-consistency: n=3 samples per judge at temp=0.3, take median.
    Always run pairwise in both orders (swap-symmetry) when used for A/B tests.
    """
    per_axis_per_judge: list[JudgeAxisScore] = Field(default_factory=list)
    aggregated: dict[RubricAxis, float] = Field(default_factory=dict)
    composite: float = 0.0
    passes_auto_publish: bool = False
    voice_floor_met: bool = True
    novelty_floor_met: bool = True


# ---------------------------------------------------------------------------
# Carousel V2
# ---------------------------------------------------------------------------

class CarouselGenerationStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    DESIGNING = "designing"
    SKEPTIC = "skeptic"
    REFLEXION = "reflexion"
    RENDERING = "rendering"
    AWAITING_REVIEW = "awaiting_review"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ABANDONED = "abandoned"
    FAILED = "failed"


class CarouselV2(BaseModel):
    """Canonical V2 carousel shape. Serialised into ``carousel_generations``
    JSONB columns.
    """
    model_config = ConfigDict(use_enum_values=True)

    id: str
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    topic: str
    franchise: Optional[str] = None
    character_id: Optional[str] = None

    # Prompts that produced this carousel — stamped at generate-time so a
    # replay reconstructs the exact compile state.
    prompt_version_id: Optional[str] = None
    designer_prompt_id: Optional[str] = None
    skeptic_prompt_id: Optional[str] = None

    # Voice file applied (per-property YAML in voices/{property}.yml)
    voice_file: Optional[str] = None

    slides: list[Slide] = Field(default_factory=list)
    citations: list[AtomicFact] = Field(default_factory=list)
    rubric: Optional[CarouselRubric] = None

    revision_count: int = 0
    status: CarouselGenerationStatus = CarouselGenerationStatus.PENDING

    # Caption + hashtags + sound — populated in Phase 5
    caption: Optional[str] = None
    hashtags: list[str] = Field(default_factory=list)
    sound_id: Optional[str] = None

    # Publishing
    publish_id: Optional[str] = None
    publish_url: Optional[str] = None
    idempotency_key: Optional[str] = None

    # Timing
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Workflow input / output (Temporal-friendly — JSON-serialisable)
# ---------------------------------------------------------------------------

class CarouselWorkflowInput(BaseModel):
    """Input payload to ``GenerateCarouselWorkflow``."""
    topic: str
    franchise: Optional[str] = None
    character_id: Optional[str] = None
    angle: Optional[str] = None
    slide_count: int = 8
    voice_file: Optional[str] = None
    prompt_version_id: Optional[str] = None
    auto_publish: bool = False
    initiated_by: Optional[str] = None  # scheduler | api | manual | retry


class CarouselWorkflowResult(BaseModel):
    """Output payload from ``GenerateCarouselWorkflow``."""
    generation_id: str
    carousel_id: Optional[str] = None
    status: CarouselGenerationStatus
    composite_score: Optional[float] = None
    publish_id: Optional[str] = None
    error: Optional[str] = None
