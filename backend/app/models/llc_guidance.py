"""
LLC Formation Guidance models.
Zero guides users through LLC creation for TikTok Shop, consulting, and multi-venture businesses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BusinessType(str, Enum):
    """Types of business activities for the LLC."""
    TIKTOK_SHOP = "tiktok_shop"
    CONSULTING = "consulting"
    ECOMMERCE = "ecommerce"
    CONTENT_CREATION = "content_creation"
    SOFTWARE = "software"
    DROPSHIPPING = "dropshipping"
    AFFILIATE_MARKETING = "affiliate_marketing"
    AGENCY = "agency"
    OTHER = "other"


class LLCType(str, Enum):
    """LLC structure types."""
    SINGLE_MEMBER = "single_member"
    MULTI_MEMBER = "multi_member"
    SERIES_LLC = "series_llc"


class GuidanceRequest(BaseModel):
    """Request for LLC formation guidance."""
    business_types: List[BusinessType] = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2, description="US state abbreviation")
    llc_name_ideas: List[str] = Field(default_factory=list)
    llc_type: LLCType = LLCType.SINGLE_MEMBER
    num_members: int = Field(1, ge=1, le=100)
    annual_revenue_estimate: Optional[str] = None
    has_existing_llc: bool = False
    specific_questions: Optional[str] = None


class FormationStep(BaseModel):
    """A single step in the LLC formation process."""
    step_number: int
    title: str
    description: str
    estimated_cost: Optional[str] = None
    estimated_time: Optional[str] = None
    links: List[Dict[str, str]] = Field(default_factory=list)
    tips: List[str] = Field(default_factory=list)
    required: bool = True


class GuidanceResponse(BaseModel):
    """Full LLC formation guidance response."""
    llc_name_suggestions: List[str] = Field(default_factory=list)
    recommended_state: str
    recommended_type: LLCType
    why_this_structure: str
    formation_steps: List[FormationStep] = Field(default_factory=list)
    estimated_total_cost: str
    estimated_timeline: str
    tax_considerations: List[str] = Field(default_factory=list)
    business_specific_tips: Dict[str, List[str]] = Field(default_factory=dict)
    operating_agreement_points: List[str] = Field(default_factory=list)
    next_steps_after_formation: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class StateInfo(BaseModel):
    """Basic LLC info for a US state."""
    state_code: str
    state_name: str
    filing_fee: str
    annual_fee: str
    processing_time: str
    online_filing: bool
    notes: str = ""
