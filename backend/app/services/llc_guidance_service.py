"""
LLC Formation Guidance Service.

Uses LLM + web research to guide users through LLC creation
for TikTok Shop, consulting agencies, and multi-venture businesses.
"""

import json
from functools import lru_cache
from typing import List, Dict, Any, Optional
import structlog

from app.models.llc_guidance import (
    GuidanceRequest, GuidanceResponse, FormationStep,
    StateInfo, BusinessType, LLCType,
)
from app.infrastructure.langchain_adapter import get_zero_chat_model

logger = structlog.get_logger()

# State filing info (top states for LLCs)
STATE_INFO: Dict[str, Dict[str, Any]] = {
    "WY": {"name": "Wyoming", "filing_fee": "$100", "annual_fee": "$60", "processing_time": "1-3 business days", "online": True, "notes": "No state income tax, strong asset protection, privacy-friendly"},
    "DE": {"name": "Delaware", "filing_fee": "$90", "annual_fee": "$300", "processing_time": "2-4 weeks", "online": True, "notes": "Business-friendly courts (Court of Chancery), well-established case law"},
    "NV": {"name": "Nevada", "filing_fee": "$75+$150 (business license)", "annual_fee": "$350", "processing_time": "1-3 business days", "online": True, "notes": "No state income tax, no franchise tax, strong privacy protections"},
    "NM": {"name": "New Mexico", "filing_fee": "$50", "annual_fee": "$0", "processing_time": "2-5 business days", "online": True, "notes": "Cheapest state, no annual report, no annual fee"},
    "TX": {"name": "Texas", "filing_fee": "$300", "annual_fee": "$0 (franchise tax if revenue >$2.47M)", "processing_time": "2-5 business days", "online": True, "notes": "No state income tax, large market"},
    "FL": {"name": "Florida", "filing_fee": "$125", "annual_fee": "$138.75", "processing_time": "3-5 business days", "online": True, "notes": "No state income tax, large market"},
    "CA": {"name": "California", "filing_fee": "$70", "annual_fee": "$800 (franchise tax)", "processing_time": "3-5 business days", "online": True, "notes": "Expensive $800/yr minimum tax. Only form here if you must."},
    "NY": {"name": "New York", "filing_fee": "$200", "annual_fee": "$9 (biennial)", "processing_time": "7-14 business days", "online": True, "notes": "Requires publication in 2 newspapers (~$1000-$2000). Expensive."},
    "IL": {"name": "Illinois", "filing_fee": "$150", "annual_fee": "$75", "processing_time": "5-10 business days", "online": True, "notes": "Straightforward process"},
    "OH": {"name": "Ohio", "filing_fee": "$99", "annual_fee": "$0", "processing_time": "3-5 business days", "online": True, "notes": "No annual report requirement"},
    "VA": {"name": "Virginia", "filing_fee": "$100", "annual_fee": "$50", "processing_time": "1-3 business days", "online": True, "notes": "Fast processing, reasonable fees"},
    "WA": {"name": "Washington", "filing_fee": "$200", "annual_fee": "$60", "processing_time": "3-5 business days", "online": True, "notes": "No state income tax"},
    "CO": {"name": "Colorado", "filing_fee": "$50", "annual_fee": "$10", "processing_time": "5-7 business days", "online": True, "notes": "Very affordable, low annual fee"},
    "GA": {"name": "Georgia", "filing_fee": "$100", "annual_fee": "$50", "processing_time": "5-10 business days", "online": True, "notes": "Moderate costs"},
    "AZ": {"name": "Arizona", "filing_fee": "$50", "annual_fee": "$0", "processing_time": "1-3 business days", "online": True, "notes": "No annual report, publication required in some counties"},
}

BUSINESS_TYPE_LABELS = {
    "tiktok_shop": "TikTok Shop E-commerce",
    "consulting": "Consulting Agency",
    "ecommerce": "General E-commerce",
    "content_creation": "Content Creation",
    "software": "Software Development",
    "dropshipping": "Dropshipping",
    "affiliate_marketing": "Affiliate Marketing",
    "agency": "Marketing/Creative Agency",
    "other": "Other Business",
}


class LlcGuidanceService:
    """Service for LLC formation guidance powered by LLM."""

    def get_state_info(self, state_code: str) -> Optional[StateInfo]:
        """Get LLC filing info for a specific state."""
        state_code = state_code.upper()
        info = STATE_INFO.get(state_code)
        if not info:
            return None
        return StateInfo(
            state_code=state_code,
            state_name=info["name"],
            filing_fee=info["filing_fee"],
            annual_fee=info["annual_fee"],
            processing_time=info["processing_time"],
            online_filing=info["online"],
            notes=info.get("notes", ""),
        )

    def get_all_states(self) -> List[StateInfo]:
        """Get LLC info for all tracked states."""
        return [self.get_state_info(code) for code in sorted(STATE_INFO.keys())]

    def get_recommended_states(self, business_types: List[str]) -> List[Dict[str, Any]]:
        """Recommend top states based on business type."""
        recommendations = []

        # Wyoming is almost always #1 for online businesses
        has_online = any(bt in ("tiktok_shop", "ecommerce", "dropshipping", "affiliate_marketing", "content_creation", "software")
                        for bt in business_types)
        has_consulting = "consulting" in business_types or "agency" in business_types

        if has_online:
            recommendations.append({
                "state": "WY",
                "reason": "Best for online businesses: no state income tax, $100 filing, $60/yr, strong privacy",
                "score": 95,
            })
            recommendations.append({
                "state": "NM",
                "reason": "Cheapest option: $50 filing, $0/yr annual fee, no annual reports",
                "score": 88,
            })
            recommendations.append({
                "state": "NV",
                "reason": "No state income tax, strong privacy, but higher fees ($225 filing + $350/yr)",
                "score": 82,
            })
        if has_consulting:
            recommendations.append({
                "state": "WY",
                "reason": "Best for consulting: no income tax, asset protection, professional image",
                "score": 93,
            })
            recommendations.append({
                "state": "DE",
                "reason": "Delaware is prestigious for business — investors and clients recognize it",
                "score": 85,
            })

        # Always add home state reminder
        recommendations.append({
            "state": "HOME",
            "reason": "If you operate physically in your home state, you may need to register there as a foreign LLC anyway. Consider forming in your home state to avoid double fees.",
            "score": 70,
        })

        # Deduplicate by state
        seen = set()
        unique = []
        for r in recommendations:
            if r["state"] not in seen:
                seen.add(r["state"])
                unique.append(r)

        return sorted(unique, key=lambda x: x["score"], reverse=True)

    async def generate_guidance(self, request: GuidanceRequest) -> GuidanceResponse:
        """Generate comprehensive LLC formation guidance using LLM."""
        state_code = request.state.upper()
        state_info = STATE_INFO.get(state_code, {})
        state_name = state_info.get("name", state_code)

        business_labels = [BUSINESS_TYPE_LABELS.get(bt.value, bt.value) for bt in request.business_types]
        business_desc = ", ".join(business_labels)

        # Build formation steps (deterministic base)
        steps = self._build_formation_steps(request, state_name, state_info)

        # LLM-enhanced guidance
        llm_guidance = await self._get_llm_guidance(request, state_name, business_desc)

        # Merge
        response = GuidanceResponse(
            llc_name_suggestions=llm_guidance.get("name_suggestions", []),
            recommended_state=state_code,
            recommended_type=request.llc_type,
            why_this_structure=llm_guidance.get("why_this_structure",
                f"A {request.llc_type.value.replace('_', ' ')} LLC in {state_name} provides liability protection "
                f"and tax flexibility for your {business_desc} business."),
            formation_steps=steps,
            estimated_total_cost=self._estimate_total_cost(state_info, request),
            estimated_timeline="2-4 weeks from start to fully operational",
            tax_considerations=llm_guidance.get("tax_considerations", [
                "LLCs are pass-through entities by default — profits taxed on your personal return",
                "You can elect S-Corp taxation to save on self-employment tax once profitable",
                "Keep business and personal finances completely separate",
                "Track all business expenses for deductions",
            ]),
            business_specific_tips=llm_guidance.get("business_tips", {}),
            operating_agreement_points=llm_guidance.get("operating_agreement", [
                "Member roles and responsibilities",
                "Profit/loss distribution",
                "Voting rights and decision-making process",
                "What happens if a member leaves",
                "Dissolution procedures",
            ]),
            next_steps_after_formation=llm_guidance.get("next_steps", [
                "Open a business bank account (recommended: Mercury, Relay, or Chase Business)",
                "Get business insurance (general liability at minimum)",
                "Set up accounting software (Wave is free, QuickBooks for more features)",
                "Register for any required state/local business licenses",
                "Set up a registered agent if you didn't during filing",
            ]),
            warnings=llm_guidance.get("warnings", []),
        )

        return response

    def _build_formation_steps(
        self, request: GuidanceRequest, state_name: str, state_info: dict
    ) -> List[FormationStep]:
        """Build deterministic LLC formation steps."""
        steps = []
        step_num = 1

        # Step 1: Choose a name
        steps.append(FormationStep(
            step_number=step_num,
            title="Choose Your LLC Name",
            description=(
                f"Your LLC name must be unique in {state_name} and include 'LLC' or 'Limited Liability Company'. "
                f"Search the {state_name} Secretary of State website to check availability."
            ),
            estimated_cost="$0",
            estimated_time="1-2 days",
            tips=[
                "Keep it broad if you plan multiple business activities under one LLC",
                "Avoid names too similar to existing businesses",
                "Consider a DBA (Doing Business As) if you want a different public-facing name",
                "For a multi-venture LLC, pick a holding-company style name (e.g., 'Apex Ventures LLC')",
            ],
        ))
        step_num += 1

        # Step 2: Registered agent
        steps.append(FormationStep(
            step_number=step_num,
            title="Designate a Registered Agent",
            description=(
                f"A registered agent receives legal documents on behalf of your LLC. "
                f"You can be your own agent (free) or use a service ($50-$150/yr)."
            ),
            estimated_cost="$0-$150/yr",
            estimated_time="Same day",
            tips=[
                "If forming in a state you don't live in, you MUST use a registered agent service",
                "Popular services: Northwest Registered Agent ($125/yr), Incfile (free first year)",
                "Being your own agent means your home address is public record",
            ],
        ))
        step_num += 1

        # Step 3: File Articles of Organization
        filing_fee = state_info.get("filing_fee", "varies")
        processing = state_info.get("processing_time", "varies")
        steps.append(FormationStep(
            step_number=step_num,
            title="File Articles of Organization",
            description=(
                f"File your Articles of Organization with the {state_name} Secretary of State. "
                f"Filing fee: {filing_fee}. Processing time: {processing}."
            ),
            estimated_cost=filing_fee,
            estimated_time=processing,
            tips=[
                "Most states offer online filing — faster and cheaper",
                "You'll need: LLC name, registered agent info, member names, business address",
                "Some states allow expedited processing for an additional fee",
            ],
            required=True,
        ))
        step_num += 1

        # Step 4: Get an EIN
        steps.append(FormationStep(
            step_number=step_num,
            title="Get an EIN (Employer Identification Number)",
            description=(
                "Apply for a free EIN from the IRS. This is your LLC's tax ID number, "
                "needed for bank accounts, hiring, and tax filing."
            ),
            estimated_cost="$0 (free from IRS)",
            estimated_time="Instant online, or 4 weeks by mail",
            links=[{"text": "IRS EIN Application", "url": "https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online"}],
            tips=[
                "Apply online at irs.gov — you get it instantly",
                "You need an SSN or ITIN to apply",
                "Even single-member LLCs should get an EIN (don't use your SSN for business)",
            ],
            required=True,
        ))
        step_num += 1

        # Step 5: Operating Agreement
        steps.append(FormationStep(
            step_number=step_num,
            title="Create an Operating Agreement",
            description=(
                "An operating agreement defines how your LLC is managed, how profits are split, "
                "and what happens if things change. Required in some states, recommended in all."
            ),
            estimated_cost="$0 (DIY) to $500 (attorney)",
            estimated_time="1-3 days",
            tips=[
                "Even single-member LLCs need one — it proves your LLC is a separate entity",
                "Free templates available from Northwest, LegalZoom, or your state bar",
                "For multi-member LLCs, ALWAYS have an attorney review it",
                "Cover: profit distribution, voting, new members, departure, dissolution",
            ],
            required=True,
        ))
        step_num += 1

        # Step 6: Business bank account
        steps.append(FormationStep(
            step_number=step_num,
            title="Open a Business Bank Account",
            description=(
                "Open a dedicated business checking account. Never mix personal and business funds — "
                "this is critical for maintaining your LLC's liability protection."
            ),
            estimated_cost="$0 (most business accounts are free)",
            estimated_time="1-3 days",
            tips=[
                "You'll need: EIN, Articles of Organization, Operating Agreement, and ID",
                "Mercury and Relay are great for online businesses (no fees, modern UI)",
                "Chase and Bank of America are good if you want physical branches",
                "Get a business credit card too — builds business credit",
            ],
            required=True,
        ))
        step_num += 1

        # Step 7: Business licenses
        has_tiktok = any(bt.value in ("tiktok_shop", "ecommerce", "dropshipping") for bt in request.business_types)
        if has_tiktok:
            steps.append(FormationStep(
                step_number=step_num,
                title="Get a Reseller's Permit / Sales Tax ID",
                description=(
                    "Since you're selling products, you need a sales tax permit. "
                    "This lets you collect sales tax from customers and buy wholesale without paying tax."
                ),
                estimated_cost="$0-$50 (varies by state)",
                estimated_time="1-5 business days",
                tips=[
                    "Apply through your state's Department of Revenue",
                    "TikTok Shop handles sales tax collection in most states, but you still need the permit",
                    "Keep this number — suppliers will ask for it when you buy wholesale",
                ],
                required=True,
            ))
            step_num += 1

        # Step 8: Connect to platforms
        if has_tiktok:
            steps.append(FormationStep(
                step_number=step_num,
                title="Link LLC to TikTok Shop Seller Center",
                description=(
                    "Update your TikTok Shop seller account with your LLC information. "
                    "This legitimizes your shop and is required for higher selling limits."
                ),
                estimated_cost="$0",
                estimated_time="1-2 days for verification",
                links=[{"text": "TikTok Seller Center", "url": "https://seller-us.tiktok.com"}],
                tips=[
                    "Upload your EIN, Articles of Organization, and business bank info",
                    "Having an LLC can increase your daily selling limits",
                    "Use your business address, not personal",
                ],
            ))
            step_num += 1

        # Step 9: Insurance
        steps.append(FormationStep(
            step_number=step_num,
            title="Get Business Insurance",
            description=(
                "General liability insurance protects your LLC from lawsuits. "
                "Product liability is important if you're selling physical products."
            ),
            estimated_cost="$30-$100/month",
            estimated_time="Same day",
            tips=[
                "General liability: covers customer injuries, property damage",
                "Product liability: essential if selling physical products on TikTok Shop",
                "Professional liability (E&O): important for consulting/agency work",
                "Hiscox, Next Insurance, and Hartford are popular for small LLCs",
            ],
        ))
        step_num += 1

        # Step 10: Accounting
        steps.append(FormationStep(
            step_number=step_num,
            title="Set Up Accounting & Tax Tracking",
            description=(
                "Track income and expenses from day one. This saves massive headaches at tax time "
                "and ensures you can prove your LLC is a real business."
            ),
            estimated_cost="$0 (Wave) to $30/mo (QuickBooks)",
            estimated_time="1-2 hours setup",
            tips=[
                "Wave is free and great for simple businesses",
                "QuickBooks Self-Employed is good for single-member LLCs ($15/mo)",
                "Save 25-30% of profits for taxes (income + self-employment)",
                "Consider S-Corp election once you're making $50K+ profit/year to save on self-employment tax",
            ],
        ))

        return steps

    def _estimate_total_cost(self, state_info: dict, request: GuidanceRequest) -> str:
        """Estimate total formation cost."""
        filing = state_info.get("filing_fee", "$100-$300")
        # Extract first number from filing fee string
        import re
        nums = re.findall(r'\d+', filing)
        base = int(nums[0]) if nums else 150

        # Add registered agent if out of state
        agent_cost = 125  # typical registered agent
        total_min = base
        total_max = base + agent_cost + 100  # insurance first month

        return f"${total_min}-${total_max} (filing + setup), plus ongoing $50-$200/month (insurance, accounting, annual fees)"

    async def _get_llm_guidance(
        self, request: GuidanceRequest, state_name: str, business_desc: str
    ) -> Dict[str, Any]:
        """Get LLM-enhanced guidance for the specific business setup."""
        try:
            from app.infrastructure.unified_llm_client import get_unified_llm_client

            client = get_unified_llm_client()

            name_ideas_text = ""
            if request.llc_name_ideas:
                name_ideas_text = f"\nUser's name ideas: {', '.join(request.llc_name_ideas)}"

            questions_text = ""
            if request.specific_questions:
                questions_text = f"\nUser's specific questions: {request.specific_questions}"

            prompt = (
                f"Generate LLC formation guidance for this specific situation:\n\n"
                f"Business activities: {business_desc}\n"
                f"State: {state_name}\n"
                f"LLC type: {request.llc_type.value.replace('_', ' ')}\n"
                f"Number of members: {request.num_members}\n"
                f"Revenue estimate: {request.annual_revenue_estimate or 'Not specified'}\n"
                f"Has existing LLC: {request.has_existing_llc}\n"
                f"{name_ideas_text}{questions_text}\n\n"
                f"Provide:\n"
                f"- name_suggestions: array of 5 LLC name suggestions (broad enough for all listed activities)\n"
                f"- why_this_structure: 2-3 sentences on why this LLC type is right for them\n"
                f"- tax_considerations: array of 4-6 specific tax tips for this business combo\n"
                f"- business_tips: object where keys are business type names and values are arrays of 3-4 tips specific to that business type\n"
                f"- operating_agreement: array of 5-7 key points for the operating agreement\n"
                f"- next_steps: array of 5-7 things to do after formation\n"
                f"- warnings: array of 2-4 important warnings or common mistakes\n\n"
                f"Be specific and actionable."
            )

            result = await client.structured_chat(
                prompt=prompt,
                system="You are a business formation expert.",
                task_type="structured_output",
                temperature=0.3,
                max_tokens=4096,
                output_schema={
                    "name_suggestions": ["str"],
                    "why_this_structure": "str",
                    "tax_considerations": ["str"],
                    "business_tips": {},
                    "operating_agreement": ["str"],
                    "next_steps": ["str"],
                    "warnings": ["str"],
                },
            )

            return result if isinstance(result, dict) else {}

        except Exception as e:
            logger.warning("llc_llm_guidance_failed", error=str(e))
            return {}

    async def answer_question(self, question: str, context: Optional[Dict] = None) -> str:
        """Answer a specific LLC-related question using LLM."""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = get_zero_chat_model(task_type="analysis", temperature=0.3)
            llm.num_predict = 2048

            context_text = ""
            if context:
                context_text = f"\nUser's business context: {json.dumps(context)}"

            prompt = (
                f"Answer this LLC/business formation question:\n\n"
                f"{question}{context_text}\n\n"
                f"Be specific, actionable, and concise. "
                f"If this requires professional legal/tax advice, say so."
            )

            response = await llm.ainvoke([
                SystemMessage(content="You are a business formation expert. Give practical, actionable advice. Always note when professional legal or tax advice is needed. /no_think"),
                HumanMessage(content=prompt),
            ])

            return response.content or "I couldn't generate a response. Please try rephrasing your question."

        except Exception as e:
            logger.error("llc_question_failed", error=str(e))
            return "Sorry, I couldn't process that question right now. The LLM service may be unavailable."


@lru_cache()
def get_llc_guidance_service() -> LlcGuidanceService:
    return LlcGuidanceService()
