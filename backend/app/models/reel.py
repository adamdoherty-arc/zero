"""Motivation Reels — Pydantic models.

The canonical shapes that flow through the reel pipeline
(``app.services.reels.reel_orchestrator`` directly, or
``app.workflows.reel_workflow.GenerateMotivationReelWorkflow`` via Temporal).

This is a *parallel* plane to ``app.models.carousel`` — it deliberately reuses
none of the character-trivia machinery (atomic facts, trust tiers, 11-stage
image funnel) because motivation reels are quote-driven video, not
fact-grounded static carousels. What the two share is the cross-cutting
learning machinery (bandit / exemplar / drift / judge panel), which keys on
plain strings (``decision_point`` / ``franchise`` / ``content_type``) and needs
no model coupling.

Design notes:

- **Attribution is a hard gate.** Misattributed quotes are the #1 credibility
  killer in this niche. ``QuoteCard.attribution`` carries the verdict and only
  ``VERIFIED`` / ``ANONYMOUS`` quotes are eligible to publish with an author
  shown. See ``services/reels/quote_source_service``.
- **Music must be bakeable.** Only ``BAKEABLE_LICENSES`` may be muxed into the
  MP4 — the legacy copyrighted ``music_tracks`` rows are never eligible.
- **One master MP4 serves all platforms** (TikTok / IG Reels / YT Shorts); the
  per-platform differences live in ``PlatformPublish`` records, not the encode.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Niche / mood taxonomy
# ---------------------------------------------------------------------------

class ReelSubNiche(str, Enum):
    """Ranked by monetization × competition (see plan content-strategy block).

    The bandit learns which of these actually perform; this is the seed set.
    """
    STOICISM = "stoicism"
    DISCIPLINE = "discipline"
    WEALTH_MINDSET = "wealth_mindset"
    SELF_IMPROVEMENT = "self_improvement"
    FAITH = "faith"
    GRINDSET = "grindset"
    MENTAL_HEALTH = "mental_health"
    ENTREPRENEURSHIP = "entrepreneurship"
    AFFIRMATIONS = "affirmations"


class ReelMood(str, Enum):
    EPIC = "epic"
    CALM = "calm"
    HOPEFUL = "hopeful"
    DARK = "dark"
    INTENSE = "intense"
    REFLECTIVE = "reflective"
    UPLIFTING = "uplifting"


# Default mood per sub-niche — a sensible prior the bandit can override.
SUBNICHE_DEFAULT_MOOD: dict[str, str] = {
    ReelSubNiche.STOICISM.value: ReelMood.REFLECTIVE.value,
    ReelSubNiche.DISCIPLINE.value: ReelMood.INTENSE.value,
    ReelSubNiche.WEALTH_MINDSET.value: ReelMood.EPIC.value,
    ReelSubNiche.SELF_IMPROVEMENT.value: ReelMood.HOPEFUL.value,
    ReelSubNiche.FAITH.value: ReelMood.UPLIFTING.value,
    ReelSubNiche.GRINDSET.value: ReelMood.INTENSE.value,
    ReelSubNiche.MENTAL_HEALTH.value: ReelMood.CALM.value,
    ReelSubNiche.ENTREPRENEURSHIP.value: ReelMood.EPIC.value,
    ReelSubNiche.AFFIRMATIONS.value: ReelMood.CALM.value,
}


# ---------------------------------------------------------------------------
# Quote ledger
# ---------------------------------------------------------------------------

class QuoteAttribution(str, Enum):
    """Verdict from the attribution gate.

    Only ``VERIFIED`` and ``ANONYMOUS`` are publish-eligible with confidence.
    ``UNVERIFIED`` quotes may still ship but never with a confidently-stated
    author; ``DISPUTED`` (commonly-misattributed) are blocked.
    """
    VERIFIED = "verified"        # fuzzy-matched a primary / public-domain source
    ANONYMOUS = "anonymous"      # no author claimed — always safe
    UNVERIFIED = "unverified"    # candidate only, author unconfirmed
    DISPUTED = "disputed"        # commonly misattributed — block


class QuoteCard(BaseModel):
    """The atom of a motivation reel. One quote → one reel."""
    id: str
    text: str
    author: Optional[str] = None
    source_work: Optional[str] = None      # the book / speech / letter it's from
    source_url: Optional[str] = None        # primary-source URL when verified
    attribution: QuoteAttribution = QuoteAttribution.UNVERIFIED
    attribution_confidence: float = 0.0     # fuzzy-match score [0, 1]
    sub_niche: Optional[str] = None
    theme: Optional[str] = None
    mood: Optional[str] = None
    novelty_score: Optional[float] = None   # 1 - max cosine vs recent posts
    is_public_domain: bool = False
    sha256: str = ""                         # dedup key (normalised text)

    @property
    def display_author(self) -> str:
        """The author string safe to render on-screen.

        Never claims an author for a disputed/unverified attribution.
        """
        if self.attribution in (QuoteAttribution.VERIFIED,) and self.author:
            return self.author
        if self.attribution == QuoteAttribution.ANONYMOUS or not self.author:
            return "Unknown"
        # Unverified but author claimed — hedge rather than assert.
        return f"{self.author} (attributed)"


# ---------------------------------------------------------------------------
# Scenes (the per-shot plan that becomes video frames)
# ---------------------------------------------------------------------------

class SceneRole(str, Enum):
    HOOK = "hook"      # scroll-stopper, first ~1.3s
    BUILD = "build"    # tension / context
    QUOTE = "quote"    # the payload line
    REVEAL = "reveal"  # the turn / punch
    CTA = "cta"        # follow / save / link


class SceneMotion(str, Enum):
    KEN_BURNS_IN = "ken_burns_in"
    KEN_BURNS_OUT = "ken_burns_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    STATIC = "static"


class CaptionAnimation(str, Enum):
    FADE = "fade"
    WORD_POP = "word_pop"       # word-by-word highlight, beat-synced (Phase 2)
    TYPEWRITER = "typewriter"
    SLIDE_UP = "slide_up"
    NONE = "none"


class ReelScene(BaseModel):
    """One shot of the reel. Rendered to a 1080×1920 frame, then animated +
    sequenced by the video-assembly stage.
    """
    scene_num: int
    role: SceneRole
    text: str                                    # on-screen text for this scene
    caption_phrases: list[str] = Field(default_factory=list)  # chunks for animated captions
    voiceover_text: Optional[str] = None         # narration for this scene (optional)
    image_prompt: Optional[str] = None           # AI-gen prompt (Phase 2)
    image_query: Optional[str] = None            # stock-search query (fallback)
    image_url: Optional[str] = None              # chosen background image
    frame_url: Optional[str] = None              # rendered slide frame (uploaded)
    duration_s: float = 3.0
    motion: SceneMotion = SceneMotion.KEN_BURNS_IN
    caption_animation: CaptionAnimation = CaptionAnimation.FADE
    transition: str = "fade"                     # transition INTO the next scene
    template: str = "reel_quote"                 # render template name


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

class MusicSource(str, Enum):
    RF_LIBRARY = "rf_library"
    GENERATED = "generated"
    TIKTOK_SOUND = "tiktok_sound"   # platform sound id — NOT bakeable


class MusicLicense(str, Enum):
    CC0 = "cc0"
    CC_BY = "cc_by"
    COMMERCIAL = "commercial"           # bought / royalty-free commercial use
    GENERATED_OWNED = "generated_owned"  # AI-gen we own the output of
    PROPRIETARY = "proprietary"          # e.g. legacy Zimmer rows — NEVER bake


# The only licenses we are allowed to mux into a monetized cross-platform MP4.
BAKEABLE_LICENSES = frozenset({
    MusicLicense.CC0,
    MusicLicense.CC_BY,
    MusicLicense.COMMERCIAL,
    MusicLicense.GENERATED_OWNED,
})


class ReelMusicTrack(BaseModel):
    """A track that can back a reel. Real audio (``storage_url``/``local_path``)
    plus the beat metadata needed to sync captions.
    """
    id: str
    source: MusicSource = MusicSource.RF_LIBRARY
    provider: Optional[str] = None        # pixabay | fma | incompetech | stability | musicgen
    title: str
    artist: Optional[str] = None
    mood: Optional[str] = None
    energy: Optional[str] = None          # low | medium | high
    bpm: Optional[float] = None
    beat_grid: list[float] = Field(default_factory=list)  # beat onset timestamps (s)
    duration_s: Optional[float] = None
    license: MusicLicense = MusicLicense.CC0
    attribution: Optional[str] = None     # required credit text for CC-BY
    storage_url: Optional[str] = None     # R2 / MinIO URL
    local_path: Optional[str] = None      # cached path inside the container
    loop_safe: bool = True                # can be cleanly looped to fit duration

    @property
    def is_bakeable(self) -> bool:
        return self.license in BAKEABLE_LICENSES


# ---------------------------------------------------------------------------
# Rubric — 9 reel-tuned axes (scored by the existing judge panel)
# ---------------------------------------------------------------------------

class ReelRubricAxis(str, Enum):
    HOOK_STRENGTH = "hook_strength"
    EMOTIONAL_RESONANCE = "emotional_resonance"
    VISUAL_QUALITY = "visual_quality"
    MUSIC_TEXT_SYNC = "music_text_sync"
    PACING_COMPLETION = "pacing_completion"
    QUOTE_AUTHENTICITY = "quote_authenticity"
    ANTI_SLOP_ORIGINALITY = "anti_slop_originality"
    CTA_CLARITY = "cta_clarity"
    SAFETY_BRAND = "safety_brand"


# Weights sum to 1.0 across the seven composite axes. CTA + safety gate
# independently (they don't roll into the weighted composite).
REEL_RUBRIC_WEIGHTS: dict[ReelRubricAxis, float] = {
    ReelRubricAxis.HOOK_STRENGTH: 0.22,
    ReelRubricAxis.EMOTIONAL_RESONANCE: 0.18,
    ReelRubricAxis.VISUAL_QUALITY: 0.15,
    ReelRubricAxis.MUSIC_TEXT_SYNC: 0.12,
    ReelRubricAxis.PACING_COMPLETION: 0.12,
    ReelRubricAxis.QUOTE_AUTHENTICITY: 0.11,
    ReelRubricAxis.ANTI_SLOP_ORIGINALITY: 0.10,
    ReelRubricAxis.CTA_CLARITY: 0.0,   # gate, not weighted
    ReelRubricAxis.SAFETY_BRAND: 0.0,  # gate, not weighted
}

REEL_AUTO_PUBLISH_THRESHOLD = 7.5
REEL_QUOTE_AUTHENTICITY_FLOOR = 6.0
REEL_ANTI_SLOP_FLOOR = 5.0


class ReelRubric(BaseModel):
    """Aggregated judge scores + gate verdicts for one reel."""
    aggregated: dict[str, float] = Field(default_factory=dict)
    composite: float = 0.0
    passes_auto_publish: bool = False
    quote_authenticity_floor_met: bool = True
    anti_slop_floor_met: bool = True
    rationale: Optional[str] = None


# ---------------------------------------------------------------------------
# Status + platform publishing
# ---------------------------------------------------------------------------

class ReelGenerationStatus(str, Enum):
    PENDING = "pending"
    SOURCING = "sourcing"
    CURATING = "curating"
    PLANNING = "planning"
    SOURCING_VISUALS = "sourcing_visuals"
    RENDERING = "rendering"
    VOICING = "voicing"
    SCORING = "scoring"
    ASSEMBLING = "assembling"
    AWAITING_REVIEW = "awaiting_review"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ABANDONED = "abandoned"
    FAILED = "failed"


class PlatformName(str, Enum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"


class PlatformPublish(BaseModel):
    """One publish attempt of a reel to one platform."""
    platform: str
    post_id: Optional[str] = None
    publish_url: Optional[str] = None
    status: str = "pending"             # pending | published | dry_run | failed | skipped
    error: Optional[str] = None
    idempotency_key: Optional[str] = None
    dry_run: bool = False
    published_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# The reel
# ---------------------------------------------------------------------------

class MotivationReel(BaseModel):
    """Canonical reel shape. Serialised into ``reel_generations`` JSONB columns."""
    model_config = ConfigDict(use_enum_values=True)

    id: str
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None

    sub_niche: Optional[str] = None
    theme: Optional[str] = None
    mood: Optional[str] = None

    quote: Optional[QuoteCard] = None
    scenes: list[ReelScene] = Field(default_factory=list)
    music_track: Optional[ReelMusicTrack] = None

    voiceover: bool = False
    voiceover_url: Optional[str] = None

    # Final video
    duration_s: Optional[float] = None
    video_url: Optional[str] = None
    video_sha256: Optional[str] = None
    visual_style: Optional[str] = None   # bandit arm: ai_gen | stock | gradient

    # Copy
    caption: Optional[str] = None
    hashtags: list[str] = Field(default_factory=list)
    cta_text: Optional[str] = None
    cta_link: Optional[str] = None

    # Quality
    rubric: Optional[ReelRubric] = None
    composite_score: Optional[float] = None
    revision_count: int = 0

    status: ReelGenerationStatus = ReelGenerationStatus.PENDING
    platform_publishes: list[PlatformPublish] = Field(default_factory=list)

    # Learning provenance — which bandit arms produced this reel (for reward()).
    arms: dict[str, str] = Field(default_factory=dict)
    bandit_log_ids: dict[str, str] = Field(default_factory=dict)

    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Workflow input / output (Temporal-friendly — JSON-serialisable)
# ---------------------------------------------------------------------------

class ReelWorkflowInput(BaseModel):
    """Input payload to the reel pipeline (Temporal or direct orchestrator)."""
    sub_niche: Optional[str] = None
    theme: Optional[str] = None
    # Optional explicit quote — when omitted the sourcing stage picks one.
    quote_text: Optional[str] = None
    quote_author: Optional[str] = None
    scene_count: int = 5
    target_duration_s: float = 18.0
    voiceover: bool = False
    mood: Optional[str] = None
    music_track_id: Optional[str] = None
    visual_style: Optional[str] = None
    auto_publish: bool = False
    platforms: list[str] = Field(default_factory=lambda: [PlatformName.TIKTOK.value])
    initiated_by: Optional[str] = None  # scheduler | api | manual | retry


class ReelWorkflowResult(BaseModel):
    """Output payload from the reel pipeline."""
    generation_id: str
    reel_id: Optional[str] = None
    status: ReelGenerationStatus
    video_url: Optional[str] = None
    duration_s: Optional[float] = None
    composite_score: Optional[float] = None
    platform_publishes: list[PlatformPublish] = Field(default_factory=list)
    error: Optional[str] = None
