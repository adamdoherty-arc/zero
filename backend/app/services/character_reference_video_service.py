"""
Character Reference Video Service.

Main orchestrator for the phone-to-Zero TikTok ingest pipeline:
  pending -> downloading -> downloaded -> transcribing -> analyzing -> ready

State advances via `process_pending()` called by a scheduler job. Each tick
claims up to `batch_size` rows atomically and runs them through the pipeline.

Intent-dispatched LLM analysis:
  - inspiration : style / hook / pacing / structure
  - facts       : extract factual claims about an assigned character
  - discovery   : identify a new subject character + seed facts
  - inbox       : run inspiration + discovery (and facts if character attached)
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional, Tuple

import aiohttp
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    CharacterModel,
    CharacterReferenceVideoModel,
)
from app.infrastructure.database import get_session
from app.infrastructure.json_utils import llm_retry, sanitize_for_prompt
from app.infrastructure.unified_llm_client import get_unified_llm_client
from app.models.character_reference_video import (
    AssignCharacterRequest,
    ApplyFactsResponse,
    CharacterReferenceVideo,
    CharacterReferenceVideoCreate,
    ExtractedFact,
    ProposedCharacter,
    PromoteResponse,
    RefVideoIntent,
    RefVideoStatus,
    StyleAnalysis,
)
from app.services.video_download_service import (
    VideoDownloadError,
    download_tiktok,
    extract_audio,
    normalize_tiktok_url,
)

logger = structlog.get_logger()


# --- Workspace layout -------------------------------------------------------

WORKSPACE_ROOT = Path("workspace") / "character_content" / "reference_videos"


def _reference_dir(ref_id: str) -> Path:
    """Return the local filesystem dir for a given reference video."""
    return WORKSPACE_ROOT / ref_id


# --- Lazy Whisper singleton -------------------------------------------------

_whisper_model = None


def _get_whisper_model():
    """Return a cached faster-whisper model. Lazy-imported to keep startup fast.

    Mirrors the pattern in `audio_service.py`: cpu + int8 is default, override
    via env `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE`.
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed. pip install faster-whisper"
        ) from e

    import os

    device = os.getenv("WHISPER_DEVICE", "auto")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    model_size = os.getenv("REF_VIDEO_WHISPER_MODEL", "base")

    _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("ref_video_whisper_loaded", model=model_size, device=device, compute_type=compute_type)
    return _whisper_model


# --- Service ----------------------------------------------------------------


class CharacterReferenceVideoService:
    """Manage character reference videos: ingest, transcribe, analyze, promote."""

    # ------------------------- helpers -------------------------

    @staticmethod
    def _generate_id() -> str:
        return f"cref-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _fact_hash(text: str) -> str:
        norm = " ".join((text or "").lower().split())
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()

    def _model_to_pydantic(self, row: CharacterReferenceVideoModel) -> CharacterReferenceVideo:
        try:
            intent = RefVideoIntent(row.intent or "inbox")
        except ValueError:
            intent = RefVideoIntent.inbox
        try:
            status = RefVideoStatus(row.status or "pending")
        except ValueError:
            status = RefVideoStatus.pending

        style = None
        if row.style_analysis:
            try:
                style = StyleAnalysis(**row.style_analysis)
            except (TypeError, ValueError, KeyError, AttributeError):
                style = None

        facts = None
        if row.extracted_facts:
            try:
                facts = [ExtractedFact(**f) for f in row.extracted_facts]
            except (TypeError, ValueError, KeyError, AttributeError):
                facts = None

        proposed = None
        if row.proposed_character:
            try:
                proposed = ProposedCharacter(**row.proposed_character)
            except (TypeError, ValueError, KeyError, AttributeError):
                proposed = None

        return CharacterReferenceVideo(
            id=row.id,
            tiktok_url=row.tiktok_url,
            tiktok_video_id=row.tiktok_video_id,
            character_id=row.character_id,
            intent=intent,
            status=status,
            error_message=row.error_message,
            retry_count=row.retry_count or 0,
            title=row.title,
            author_name=row.author_name,
            author_url=row.author_url,
            caption=row.caption,
            hashtags=row.hashtags or [],
            duration_seconds=row.duration_seconds,
            thumbnail_url=row.thumbnail_url,
            views=row.views,
            likes=row.likes,
            video_path=row.video_path,
            thumbnail_path=row.thumbnail_path,
            audio_path=row.audio_path,
            file_size_bytes=row.file_size_bytes,
            transcript=row.transcript,
            transcript_language=row.transcript_language,
            transcribed_at=row.transcribed_at,
            style_analysis=style,
            extracted_facts=facts,
            proposed_character=proposed,
            analyzed_at=row.analyzed_at,
            notes=row.notes,
            promoted_character_id=row.promoted_character_id,
            applied_fact_count=row.applied_fact_count or 0,
            created_at=row.created_at or self._now(),
            updated_at=row.updated_at,
        )

    # ------------------------- CRUD -------------------------

    async def create(self, data: CharacterReferenceVideoCreate) -> CharacterReferenceVideo:
        """Create a reference video row from a full create payload (UI path)."""
        canonical, video_id = await normalize_tiktok_url(data.tiktok_url)

        # Dedup: if (video_id, character_id) already exists, return it
        if video_id:
            async with get_session() as session:
                existing_q = select(CharacterReferenceVideoModel).where(
                    CharacterReferenceVideoModel.tiktok_video_id == video_id,
                    CharacterReferenceVideoModel.character_id == data.character_id,
                )
                existing = (await session.execute(existing_q)).scalar_one_or_none()
                if existing:
                    logger.info("cref_duplicate_ingest_skipped", id=existing.id, video_id=video_id)
                    return self._model_to_pydantic(existing)

        async with get_session() as session:
            row = CharacterReferenceVideoModel(
                id=self._generate_id(),
                tiktok_url=canonical,
                tiktok_video_id=video_id,
                character_id=data.character_id,
                intent=(data.intent or RefVideoIntent.inbox).value,
                status=RefVideoStatus.pending.value,
                notes=data.notes,
            )
            session.add(row)
            await session.flush()
            return self._model_to_pydantic(row)

    async def ingest_simple(
        self,
        url: Optional[str],
        text: Optional[str] = None,
    ) -> CharacterReferenceVideo:
        """Simplified ingest used by the Android share intent.

        Accepts either a URL directly or arbitrary shared text (the share sheet
        sometimes passes caption + URL). Extracts the first TikTok-ish URL.
        """
        source = (url or text or "").strip()
        if not source:
            raise ValueError("no url or text provided")

        # If caller passed shared text like "Check this out! https://vm.tiktok.com/xyz"
        extracted = _extract_first_url(source)
        if extracted:
            source = extracted

        return await self.create(
            CharacterReferenceVideoCreate(
                tiktok_url=source,
                intent=RefVideoIntent.inbox,
            )
        )

    async def get(self, ref_id: str) -> Optional[CharacterReferenceVideo]:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            return self._model_to_pydantic(row) if row else None

    async def list(
        self,
        character_id: Optional[str] = None,
        intent: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CharacterReferenceVideo]:
        async with get_session() as session:
            q = select(CharacterReferenceVideoModel).order_by(
                CharacterReferenceVideoModel.created_at.desc()
            )
            if character_id:
                q = q.where(CharacterReferenceVideoModel.character_id == character_id)
            if intent:
                q = q.where(CharacterReferenceVideoModel.intent == intent)
            if status:
                q = q.where(CharacterReferenceVideoModel.status == status)
            q = q.offset(offset).limit(limit)
            rows = (await session.execute(q)).scalars().all()
            return [self._model_to_pydantic(r) for r in rows]

    async def update(
        self,
        ref_id: str,
        intent: Optional[RefVideoIntent] = None,
        character_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[CharacterReferenceVideo]:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return None
            if intent is not None:
                row.intent = intent.value
            if character_id is not None:
                row.character_id = character_id or None
            if notes is not None:
                row.notes = notes
            await session.flush()
            return self._model_to_pydantic(row)

    async def delete(self, ref_id: str) -> bool:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return False
            await session.delete(row)
            await session.flush()

        # Also remove on-disk files
        dir_path = _reference_dir(ref_id)
        if dir_path.exists():
            try:
                shutil.rmtree(dir_path)
            except (OSError, PermissionError) as e:
                logger.warning("cref_dir_delete_failed", id=ref_id, error=str(e))
        return True

    async def retry(self, ref_id: str) -> Optional[CharacterReferenceVideo]:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return None
            row.status = RefVideoStatus.pending.value
            row.error_message = None
            await session.flush()
            return self._model_to_pydantic(row)

    # ------------------------- state machine -------------------------

    async def process_pending(self, batch_size: int = 5) -> int:
        """Advance up to `batch_size` pending rows. Returns number processed."""
        processed = 0
        for _ in range(batch_size):
            claim = await self._claim_one_pending()
            if not claim:
                break
            ref_id = claim
            try:
                await self._run_pipeline(ref_id)
                processed += 1
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ValueError,
                KeyError,
                AttributeError,
                RuntimeError,
                TypeError,
                SQLAlchemyError,
                OSError,
            ) as e:
                logger.exception("cref_pipeline_error", id=ref_id, error=str(e))
                await self._mark_failed(ref_id, str(e)[:500])
        return processed

    async def _claim_one_pending(self) -> Optional[str]:
        """Atomically move one `pending` row to `downloading`. Returns its id."""
        async with get_session() as session:
            sub = (
                select(CharacterReferenceVideoModel.id)
                .where(CharacterReferenceVideoModel.status == RefVideoStatus.pending.value)
                .order_by(CharacterReferenceVideoModel.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            candidate = (await session.execute(sub)).scalar_one_or_none()
            if not candidate:
                return None

            stmt = (
                update(CharacterReferenceVideoModel)
                .where(
                    CharacterReferenceVideoModel.id == candidate,
                    CharacterReferenceVideoModel.status == RefVideoStatus.pending.value,
                )
                .values(status=RefVideoStatus.downloading.value)
                .returning(CharacterReferenceVideoModel.id)
            )
            res = (await session.execute(stmt)).scalar_one_or_none()
            return res

    async def _set_status(self, ref_id: str, status: RefVideoStatus, **fields: Any) -> None:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return
            row.status = status.value
            for k, v in fields.items():
                setattr(row, k, v)
            await session.flush()

    async def _mark_failed(self, ref_id: str, message: str) -> None:
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return
            row.status = RefVideoStatus.failed.value
            row.error_message = message
            row.retry_count = (row.retry_count or 0) + 1
            await session.flush()

    async def _run_pipeline(self, ref_id: str) -> None:
        """Download -> extract audio -> transcribe -> analyze."""
        # Load the row snapshot
        ref = await self.get(ref_id)
        if not ref:
            return

        # 1. Download
        dir_path = _reference_dir(ref_id)
        try:
            result = await download_tiktok(ref.tiktok_url, dir_path)
        except VideoDownloadError as e:
            raise RuntimeError(f"download failed: {e}") from e

        info = result.info or {}
        video_path_rel = str(result.video_path.relative_to(Path.cwd())) if result.video_path.is_absolute() else str(result.video_path)
        thumb_rel = (
            str(result.thumbnail_path.relative_to(Path.cwd()))
            if result.thumbnail_path and result.thumbnail_path.is_absolute()
            else (str(result.thumbnail_path) if result.thumbnail_path else None)
        )

        await self._set_status(
            ref_id,
            RefVideoStatus.downloaded,
            video_path=video_path_rel,
            thumbnail_path=thumb_rel,
            file_size_bytes=result.file_size_bytes,
            title=info.get("title") or info.get("description") or None,
            author_name=info.get("uploader") or info.get("channel") or info.get("creator"),
            author_url=info.get("uploader_url") or info.get("channel_url"),
            caption=info.get("description"),
            hashtags=_parse_hashtags(info),
            duration_seconds=_safe_int(info.get("duration")),
            thumbnail_url=info.get("thumbnail"),
            views=_safe_int(info.get("view_count")),
            likes=_safe_int(info.get("like_count")),
        )

        # 2. Extract audio
        audio_path = dir_path / "audio.m4a"
        try:
            await extract_audio(result.video_path, audio_path)
        except VideoDownloadError as e:
            raise RuntimeError(f"audio extract failed: {e}") from e

        audio_rel = str(audio_path)
        await self._set_status(
            ref_id,
            RefVideoStatus.transcribing,
            audio_path=audio_rel,
        )

        # 3. Transcribe
        transcript_text, language = await self._transcribe(audio_path)

        await self._set_status(
            ref_id,
            RefVideoStatus.analyzing,
            transcript=transcript_text,
            transcript_language=language,
            transcribed_at=self._now(),
        )

        # 4. Intent-dispatched analysis
        fields: dict = {"analyzed_at": self._now()}
        refreshed = await self.get(ref_id)
        intent = refreshed.intent if refreshed else ref.intent

        try:
            if intent in (RefVideoIntent.inspiration, RefVideoIntent.inbox):
                style = await self._analyze_inspiration(refreshed or ref)
                if style:
                    fields["style_analysis"] = style

            if intent == RefVideoIntent.facts and refreshed and refreshed.character_id:
                facts = await self._analyze_facts(refreshed, refreshed.character_id)
                if facts:
                    fields["extracted_facts"] = facts

            if intent in (RefVideoIntent.discovery, RefVideoIntent.inbox):
                proposed = await self._analyze_discovery(refreshed or ref)
                if proposed:
                    fields["proposed_character"] = proposed
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,
            KeyError,
            AttributeError,
            RuntimeError,
            TypeError,
            SQLAlchemyError,
            OSError,
        ) as e:
            logger.warning("cref_analysis_failed", id=ref_id, intent=str(intent), error=str(e))

        await self._set_status(ref_id, RefVideoStatus.ready, **fields)
        logger.info("cref_pipeline_ready", id=ref_id, intent=str(intent))

    # ------------------------- transcription -------------------------

    async def _transcribe(self, audio_path: Path) -> Tuple[str, Optional[str]]:
        """Run faster-whisper on the extracted audio. Returns (text, language)."""
        import asyncio

        def _do() -> Tuple[str, Optional[str]]:
            model = _get_whisper_model()
            segments, info = model.transcribe(
                str(audio_path),
                beam_size=1,
                vad_filter=True,
            )
            pieces: List[str] = []
            for seg in segments:
                pieces.append(seg.text)
            return ("".join(pieces).strip(), getattr(info, "language", None))

        return await asyncio.to_thread(_do)

    # ------------------------- LLM analysis -------------------------

    @llm_retry
    async def _call_llm_structured(
        self,
        prompt: str,
        system: str,
        schema_hint: dict,
        task_type: str = "extraction",
        max_tokens: int = 2048,
    ) -> Any:
        client = get_unified_llm_client()
        return await client.structured_chat(
            prompt=prompt,
            system=system,
            task_type=task_type,
            temperature=0.5,
            max_tokens=max_tokens,
            output_schema=schema_hint,
        )

    def _context_block(self, ref: CharacterReferenceVideo) -> str:
        caption = sanitize_for_prompt(ref.caption or ref.title or "", max_length=600)
        transcript = sanitize_for_prompt(ref.transcript or "", max_length=3000)
        hashtags = ", ".join(ref.hashtags or [])[:300]
        return (
            f"Author: {ref.author_name or 'Unknown'}\n"
            f"Caption: {caption}\n"
            f"Hashtags: {hashtags}\n"
            f"Duration: {ref.duration_seconds or '?'} seconds\n\n"
            f"Transcript:\n{transcript}\n"
        )

    async def _analyze_inspiration(self, ref: CharacterReferenceVideo) -> Optional[dict]:
        if not (ref.transcript or ref.caption):
            return None
        prompt = (
            "Analyze this TikTok video as inspiration for short-form content style.\n\n"
            f"{self._context_block(ref)}\n"
            "Return JSON with these keys:\n"
            "  hook: the exact technique used in the first 2-3 seconds\n"
            "  structure: section breakdown (hook / body / cta etc)\n"
            "  pacing: fast|medium|slow and why\n"
            "  visual_style: b-roll, text overlays, transitions, framing\n"
            "  transitions: describe any notable cuts or effects\n"
            "  estimated_engagement: low|medium|high|viral and why\n"
        )
        data = await self._call_llm_structured(
            prompt=prompt,
            system="You are a short-form video content analyst.",
            schema_hint={
                "hook": "str",
                "structure": "str",
                "pacing": "str",
                "visual_style": "str",
                "transitions": "str",
                "estimated_engagement": "str",
            },
        )
        if isinstance(data, dict):
            return {k: _coerce_str(data.get(k)) for k in (
                "hook", "structure", "pacing", "visual_style", "transitions", "estimated_engagement"
            )}
        return None

    async def _analyze_facts(
        self,
        ref: CharacterReferenceVideo,
        character_id: str,
    ) -> Optional[list]:
        if not (ref.transcript or ref.caption):
            return None

        # Load character for context
        async with get_session() as session:
            char = await session.get(CharacterModel, character_id)
            if not char:
                return None
            char_name = char.name
            char_universe = char.universe
            char_desc = sanitize_for_prompt(char.description or "", 400)

        prompt = (
            f"Extract factual claims about the character {char_name} ({char_universe}) "
            f"from this TikTok video.\n\n"
            f"Character description: {char_desc}\n\n"
            f"{self._context_block(ref)}\n"
            "ONLY extract claims that are directly about this character. Ignore unrelated commentary.\n"
            "Return JSON: {\"facts\": [{\"text\": \"short factual claim\", "
            "\"category\": \"backstory|powers|relationships|trivia|quote\", "
            "\"surprise_score\": 0.0..1.0, \"source_timecode\": \"00:12\"}]}\n"
            "Omit any claim you cannot verify from the video content."
        )
        data = await self._call_llm_structured(
            prompt=prompt,
            system="You are a careful fact extractor. Do not invent facts.",
            schema_hint={"facts": [{"text": "str", "category": "str", "surprise_score": 0.5, "source_timecode": "str"}]},
            max_tokens=3000,
        )
        if isinstance(data, dict):
            raw = data.get("facts") or []
        elif isinstance(data, list):
            raw = data
        else:
            raw = []

        cleaned: List[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = (item.get("text") or "").strip()
            if not text:
                continue
            try:
                score = float(item.get("surprise_score") or 0.5)
            except (ValueError, TypeError):
                score = 0.5
            cleaned.append({
                "text": text[:500],
                "category": (item.get("category") or "trivia")[:40],
                "surprise_score": max(0.0, min(1.0, score)),
                "source_timecode": (item.get("source_timecode") or "")[:20] or None,
            })
        return cleaned or None

    async def _analyze_discovery(self, ref: CharacterReferenceVideo) -> Optional[dict]:
        if not (ref.transcript or ref.caption):
            return None
        prompt = (
            "Identify the fictional character or personality this TikTok is primarily about.\n"
            "If the video is not clearly about one specific character, return {\"name\": null}.\n\n"
            f"{self._context_block(ref)}\n"
            "Return JSON: {\"name\": str|null, \"universe\": str|null, \"franchise\": str|null, "
            "\"description\": str, \"seed_facts\": [{\"text\": str, \"category\": str, "
            "\"surprise_score\": 0.5, \"source_timecode\": str|null}]}\n"
        )
        data = await self._call_llm_structured(
            prompt=prompt,
            system="You identify fictional characters and real personalities from short videos.",
            schema_hint={
                "name": "str",
                "universe": "str",
                "franchise": "str",
                "description": "str",
                "seed_facts": [{"text": "str", "category": "str", "surprise_score": 0.5, "source_timecode": "str"}],
            },
            max_tokens=2500,
        )
        if not isinstance(data, dict):
            return None
        name = (data.get("name") or "").strip() or None
        if not name:
            return {"name": None}

        raw_facts = data.get("seed_facts") or []
        seed_facts: List[dict] = []
        if isinstance(raw_facts, list):
            for f in raw_facts[:15]:
                if not isinstance(f, dict):
                    continue
                text = (f.get("text") or "").strip()
                if not text:
                    continue
                seed_facts.append({
                    "text": text[:500],
                    "category": (f.get("category") or "trivia")[:40],
                    "surprise_score": 0.5,
                    "source_timecode": (f.get("source_timecode") or "") or None,
                })

        return {
            "name": name[:200],
            "universe": (data.get("universe") or None),
            "franchise": (data.get("franchise") or None),
            "description": (data.get("description") or "")[:2000] or None,
            "seed_facts": seed_facts,
        }

    # ------------------------- actions -------------------------

    async def analyze(self, ref_id: str) -> Optional[CharacterReferenceVideo]:
        """Re-run the analysis step for an already-downloaded row."""
        ref = await self.get(ref_id)
        if not ref:
            return None
        if not ref.transcript:
            # Nothing to analyze yet; just push it back to pending
            return await self.retry(ref_id)

        fields: dict = {"analyzed_at": self._now()}
        if ref.intent in (RefVideoIntent.inspiration, RefVideoIntent.inbox):
            style = await self._analyze_inspiration(ref)
            if style:
                fields["style_analysis"] = style
        if ref.intent == RefVideoIntent.facts and ref.character_id:
            facts = await self._analyze_facts(ref, ref.character_id)
            if facts:
                fields["extracted_facts"] = facts
        if ref.intent in (RefVideoIntent.discovery, RefVideoIntent.inbox):
            proposed = await self._analyze_discovery(ref)
            if proposed:
                fields["proposed_character"] = proposed

        await self._set_status(ref_id, RefVideoStatus.ready, **fields)
        return await self.get(ref_id)

    async def assign_character(
        self,
        ref_id: str,
        request: AssignCharacterRequest,
    ) -> Optional[CharacterReferenceVideo]:
        """Attach the video to a character and re-run facts analysis."""
        async with get_session() as session:
            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if not row:
                return None
            char = await session.get(CharacterModel, request.character_id)
            if not char:
                raise ValueError("character not found")
            row.character_id = request.character_id
            row.intent = RefVideoIntent.facts.value
            await session.flush()

        # Re-run facts extraction now that we know the subject
        ref = await self.get(ref_id)
        if ref and ref.transcript:
            facts = await self._analyze_facts(ref, request.character_id)
            if facts:
                await self._set_status(
                    ref_id,
                    RefVideoStatus.ready,
                    extracted_facts=facts,
                    analyzed_at=self._now(),
                )
        return await self.get(ref_id)

    async def apply_facts(
        self,
        ref_id: str,
        fact_indexes: Optional[List[int]] = None,
    ) -> ApplyFactsResponse:
        """Merge extracted facts into `characters.fact_bank` with dedup."""
        ref = await self.get(ref_id)
        if not ref:
            raise ValueError("reference video not found")
        if not ref.character_id:
            raise ValueError("reference video has no character assigned")
        if not ref.extracted_facts:
            raise ValueError("no extracted facts to apply")

        # Pick subset if given
        if fact_indexes is not None:
            selected = [ref.extracted_facts[i] for i in fact_indexes if 0 <= i < len(ref.extracted_facts)]
        else:
            selected = list(ref.extracted_facts)

        async with get_session() as session:
            char = await session.get(CharacterModel, ref.character_id)
            if not char:
                raise ValueError("character not found")

            existing = list(char.fact_bank or [])
            existing_hashes = set()
            for f in existing:
                if isinstance(f, dict) and f.get("text"):
                    existing_hashes.add(self._fact_hash(f["text"]))

            applied = 0
            for fact in selected:
                fact_dict = fact.model_dump() if hasattr(fact, "model_dump") else dict(fact)
                text = fact_dict.get("text")
                if not text:
                    continue
                h = self._fact_hash(text)
                if h in existing_hashes:
                    continue
                existing_hashes.add(h)
                existing.append({
                    **fact_dict,
                    "source": "tiktok_reference",
                    "source_id": ref_id,
                    "added_at": self._now().isoformat(),
                })
                applied += 1

            char.fact_bank = existing

            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if row:
                row.applied_fact_count = (row.applied_fact_count or 0) + applied
            await session.flush()

            return ApplyFactsResponse(
                reference_video_id=ref_id,
                character_id=ref.character_id,
                applied_count=applied,
                total_fact_bank_size=len(existing),
            )

    async def promote_to_character(
        self,
        ref_id: str,
        name: Optional[str] = None,
        universe: Optional[str] = None,
        franchise: Optional[str] = None,
        description: Optional[str] = None,
    ) -> PromoteResponse:
        """Create a Character from the proposed_character JSON and link it."""
        ref = await self.get(ref_id)
        if not ref:
            raise ValueError("reference video not found")

        proposed = ref.proposed_character
        final_name = name or (proposed.name if proposed else None)
        if not final_name:
            raise ValueError("no character name available (pass name= or run discovery)")

        final_universe = universe or (proposed.universe if proposed else None) or "other"
        final_franchise = franchise or (proposed.franchise if proposed else None)
        final_description = description or (proposed.description if proposed else None)

        character_id = f"char-{uuid.uuid4().hex[:12]}"
        now = self._now()

        seed_facts: List[dict] = []
        if proposed and proposed.seed_facts:
            for f in proposed.seed_facts:
                fd = f.model_dump() if hasattr(f, "model_dump") else dict(f)
                seed_facts.append({
                    **fd,
                    "source": "tiktok_reference",
                    "source_id": ref_id,
                    "added_at": now.isoformat(),
                })

        async with get_session() as session:
            char = CharacterModel(
                id=character_id,
                name=final_name,
                universe=final_universe,
                franchise=final_franchise,
                description=final_description,
                research_status="pending",
                fact_bank=seed_facts,
                status="active",
            )
            session.add(char)

            row = await session.get(CharacterReferenceVideoModel, ref_id)
            if row:
                row.character_id = character_id
                row.promoted_character_id = character_id
                row.applied_fact_count = len(seed_facts)

            await session.flush()

        logger.info(
            "cref_promoted_to_character",
            ref_id=ref_id,
            character_id=character_id,
            seed_fact_count=len(seed_facts),
        )
        return PromoteResponse(
            reference_video_id=ref_id,
            character_id=character_id,
            status="created",
        )

    # ------------------------- maintenance -------------------------

    async def cleanup_old_files(self, age_days: int = 30) -> int:
        """Purge video+audio (keep thumbnail + metadata) for rows older than N days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (age_days * 86400)
        removed = 0
        async with get_session() as session:
            q = select(CharacterReferenceVideoModel).where(
                CharacterReferenceVideoModel.status == RefVideoStatus.ready.value,
                CharacterReferenceVideoModel.created_at < datetime.fromtimestamp(cutoff, tz=timezone.utc),
            )
            rows = (await session.execute(q)).scalars().all()
            for row in rows:
                for p_str in (row.video_path, row.audio_path):
                    if not p_str:
                        continue
                    p = Path(p_str)
                    if p.exists():
                        try:
                            p.unlink()
                            removed += 1
                        except OSError as e:
                            logger.warning("cref_cleanup_unlink_failed", path=str(p), error=str(e))
                row.video_path = None
                row.audio_path = None
            await session.flush()
        if removed:
            logger.info("cref_cleanup_done", removed_files=removed, age_days=age_days)
        return removed


# --- helpers ----------------------------------------------------------------


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _coerce_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:1000] if s else None


def _parse_hashtags(info: dict) -> list:
    import re as _re

    tags = info.get("tags") or []
    if tags and isinstance(tags, list):
        return [str(t).lstrip("#") for t in tags][:50]
    description = info.get("description") or ""
    return _re.findall(r"#(\w+)", description)[:50]


def _extract_first_url(text: str) -> Optional[str]:
    import re as _re

    match = _re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None


# --- singleton accessor -----------------------------------------------------


@lru_cache()
def get_character_reference_video_service() -> CharacterReferenceVideoService:
    return CharacterReferenceVideoService()
