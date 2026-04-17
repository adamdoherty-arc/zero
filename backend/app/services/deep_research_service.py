"""
Deep Research Service.
STORM-inspired multi-perspective research pipeline using LangGraph.
CEO plans outline, Gemma executes research + synthesis, CEO assembles final report.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, Any, List, Optional

import structlog
from sqlalchemy import select

from app.infrastructure.database import get_session
from app.infrastructure.unified_llm_client import get_unified_llm_client, StructuredOutputError
from app.db.models import DeepResearchReportModel
from app.models.agent_company import DeepResearchReport, DeepResearchRequest
from app.services.searxng_service import get_searxng_service

logger = structlog.get_logger()


def _orm_to_report(row: DeepResearchReportModel) -> DeepResearchReport:
    return DeepResearchReport(
        id=row.id,
        query=row.query,
        status=row.status,
        outline=row.outline,
        perspectives=row.perspectives or [],
        sources=row.sources or [],
        sections=row.sections or {},
        report_markdown=row.report_markdown,
        executive_summary=row.executive_summary,
        cost_usd=row.cost_usd,
        error=row.error,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


class DeepResearchService:
    def __init__(self):
        self._llm = get_unified_llm_client()

    async def start_research(self, req: DeepResearchRequest) -> DeepResearchReport:
        """Create a research report record and start the pipeline in the background."""
        report_id = f"dr-{uuid.uuid4().hex[:12]}"
        async with get_session() as session:
            row = DeepResearchReportModel(
                id=report_id,
                query=req.query,
                status="pending",
                perspectives=req.perspectives,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)

        # Run pipeline in background
        asyncio.create_task(self._run_pipeline(report_id, req))

        return _orm_to_report(row)

    async def get_report(self, report_id: str) -> Optional[DeepResearchReport]:
        async with get_session() as session:
            row = await session.get(DeepResearchReportModel, report_id)
            return _orm_to_report(row) if row else None

    async def list_reports(self, status: Optional[str] = None, limit: int = 20) -> List[DeepResearchReport]:
        async with get_session() as session:
            q = select(DeepResearchReportModel).order_by(DeepResearchReportModel.created_at.desc()).limit(limit)
            if status:
                q = q.where(DeepResearchReportModel.status == status)
            result = await session.execute(q)
            return [_orm_to_report(r) for r in result.scalars().all()]

    # ------------------------------------------------------------------
    # Pipeline Steps
    # ------------------------------------------------------------------

    async def _run_pipeline(self, report_id: str, req: DeepResearchRequest):
        """Full STORM-inspired pipeline: outline → research → synthesize → validate → assemble."""
        try:
            # Step 1: Generate outline (CEO / Kimi)
            await self._update_status(report_id, "outlining")
            outline = await self._generate_outline(req.query, req.perspectives)
            await self._update_field(report_id, "outline", outline)

            # Step 2: Research each perspective (Gemma via SearXNG)
            await self._update_status(report_id, "researching")
            all_sources = []
            sections = {}
            for section in outline.get("sections", []):
                section_title = section.get("title", "Untitled")
                queries = section.get("search_queries", [section_title])

                # Run SearXNG searches
                section_sources = []
                searxng = get_searxng_service()
                for query in queries[:3]:  # Max 3 queries per section
                    try:
                        results = await searxng.search(query, max_results=5)
                        for r in results:
                            source = {
                                "title": r.get("title", ""),
                                "url": r.get("url", ""),
                                "snippet": r.get("content", r.get("snippet", ""))[:500],
                                "section": section_title,
                            }
                            section_sources.append(source)
                            all_sources.append(source)
                    except Exception as e:
                        logger.warning("research_search_failed", query=query, error=str(e))

                # Synthesize section with Gemma
                section_content = await self._synthesize_section(
                    section_title, section.get("questions", []), section_sources
                )
                sections[section_title] = section_content

            await self._update_field(report_id, "sources", all_sources)
            await self._update_field(report_id, "sections", sections)

            # Step 3: Validate claims (Gemma/Validator)
            await self._update_status(report_id, "validating")
            validation = await self._validate_claims(sections, all_sources)

            # Step 4: Final assembly (CEO / Kimi)
            await self._update_status(report_id, "assembling")
            report_md, summary = await self._assemble_report(
                req.query, outline, sections, validation, all_sources
            )

            # Save completed report
            async with get_session() as session:
                row = await session.get(DeepResearchReportModel, report_id)
                row.status = "completed"
                row.report_markdown = report_md
                row.executive_summary = summary
                row.completed_at = datetime.now(timezone.utc)
                await session.commit()

            logger.info("deep_research_completed", report_id=report_id, sources=len(all_sources))

            # Record to brain
            try:
                from app.services.zero_brain_service import get_zero_brain_service
                brain = get_zero_brain_service()
                await brain.record_interaction_outcome(
                    domain="research", action_type="deep_research",
                    action_id=report_id, strategy_used="storm_pipeline",
                    actual_score=min(100, len(all_sources) * 10),
                    metrics={"sources": len(all_sources), "query": query},
                    text_for_memory=f"Deep research on '{query}': {summary[:500] if summary else 'no summary'}",
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("deep_research_failed", report_id=report_id, error=str(e))
            await self._update_status(report_id, "failed")
            await self._update_field(report_id, "error", str(e))

    async def _generate_outline(self, query: str, perspectives: List[str]) -> dict:
        """CEO generates research outline with sections and search queries."""
        prompt = (
            f"Create a research outline for: {query}\n\n"
            f"Perspectives to cover: {', '.join(perspectives)}\n\n"
            "Return JSON with:\n"
            '{"title": "Research title", '
            '"sections": [{"title": "Section name", "questions": ["key question 1", "key question 2"], '
            '"search_queries": ["search query 1", "search query 2"], "perspective": "technical|business|competitive"}], '
            '"key_terms": ["term1", "term2"]}'
        )
        try:
            return await self._llm.structured_chat(
                prompt=prompt,
                system="You are a research director. Create comprehensive research outlines with 3-5 sections.",
                task_type="planning",
                temperature=0.7,
                max_tokens=2048,
            )
        except StructuredOutputError:
            # Fallback outline
            return {
                "title": query,
                "sections": [
                    {"title": p.title(), "questions": [query], "search_queries": [f"{query} {p}"], "perspective": p}
                    for p in perspectives
                ],
                "key_terms": [],
            }

    async def _synthesize_section(self, title: str, questions: List[str], sources: List[dict]) -> str:
        """Gemma synthesizes research findings into a section."""
        source_text = "\n".join(
            f"- [{s['title']}]({s['url']}): {s['snippet']}" for s in sources[:10]
        )
        prompt = (
            f"Write a research section titled '{title}'.\n\n"
            f"Key questions to address: {json.dumps(questions)}\n\n"
            f"Sources:\n{source_text}\n\n"
            "Write 2-4 paragraphs synthesizing these sources. Include inline citations as [Source Title](url). "
            "Be factual and concise. Return JSON: {\"content\": \"markdown text\", \"key_findings\": [\"finding1\"]}"
        )
        try:
            result = await self._llm.structured_chat(
                prompt=prompt,
                system="You are a research analyst. Synthesize sources into clear, factual prose with citations.",
                task_type="summarization",
                temperature=0.3,
                max_tokens=2048,
            )
            return result.get("content", "") if isinstance(result, dict) else str(result)
        except StructuredOutputError:
            return f"*Research synthesis for '{title}' — {len(sources)} sources found.*"

    async def _validate_claims(self, sections: dict, sources: list) -> dict:
        """Validator spot-checks key claims."""
        section_summaries = "\n".join(
            f"**{title}**: {content[:200]}..." for title, content in sections.items()
        )
        prompt = (
            f"Review these research sections for accuracy:\n\n{section_summaries}\n\n"
            f"Number of sources: {len(sources)}\n\n"
            "Return JSON: {\"issues\": [\"issue1\"], \"confidence\": 0-100, \"suggestions\": [\"suggestion1\"]}"
        )
        try:
            return await self._llm.structured_chat(
                prompt=prompt,
                system="You are a fact-checker. Identify unsupported claims and logical gaps.",
                task_type="structured_output",
                temperature=0.2,
                max_tokens=1024,
            )
        except StructuredOutputError:
            return {"issues": [], "confidence": 70, "suggestions": []}

    async def _assemble_report(
        self, query: str, outline: dict, sections: dict, validation: dict, sources: list
    ) -> tuple:
        """CEO assembles final markdown report and executive summary."""
        sections_md = "\n\n".join(
            f"## {title}\n\n{content}" for title, content in sections.items()
        )

        # Build source list
        unique_sources = {}
        for s in sources:
            url = s.get("url", "")
            if url and url not in unique_sources:
                unique_sources[url] = s.get("title", url)

        sources_md = "\n".join(
            f"- [{title}]({url})" for url, title in list(unique_sources.items())[:30]
        )

        report_md = (
            f"# {outline.get('title', query)}\n\n"
            f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n\n"
            f"{sections_md}\n\n"
            f"## Sources\n\n{sources_md}\n"
        )

        # Generate executive summary with Kimi
        summary_prompt = (
            f"Write a 3-5 sentence executive summary for this research report:\n\n"
            f"Topic: {query}\n"
            f"Sections covered: {', '.join(sections.keys())}\n"
            f"Key findings: {json.dumps(validation.get('suggestions', []))}\n"
            f"Sources used: {len(unique_sources)}\n\n"
            "Return JSON: {\"summary\": \"executive summary text\"}"
        )
        try:
            summary_result = await self._llm.structured_chat(
                prompt=summary_prompt,
                system="Write concise executive summaries.",
                task_type="summarization",
                temperature=0.5,
                max_tokens=512,
            )
            summary = summary_result.get("summary", "") if isinstance(summary_result, dict) else str(summary_result)
        except StructuredOutputError:
            summary = f"Research report on '{query}' covering {len(sections)} sections with {len(unique_sources)} sources."

        return report_md, summary

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _update_status(self, report_id: str, status: str):
        async with get_session() as session:
            row = await session.get(DeepResearchReportModel, report_id)
            if row:
                row.status = status
                await session.commit()

    async def _update_field(self, report_id: str, field: str, value: Any):
        async with get_session() as session:
            row = await session.get(DeepResearchReportModel, report_id)
            if row:
                setattr(row, field, value)
                await session.commit()


@lru_cache()
def get_deep_research_service() -> DeepResearchService:
    return DeepResearchService()
