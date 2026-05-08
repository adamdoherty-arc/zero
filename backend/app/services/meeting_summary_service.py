"""Meeting summarization with map-reduce for long transcripts.

Uses the UnifiedLLMClient so routing honors LOCAL_LLM_BACKEND (vllm or ollama)
plus the budget fallback to Kimi / OpenRouter when the local backend fails.
"""

import json
import structlog

from app.infrastructure.unified_llm_client import get_unified_llm_client

logger = structlog.get_logger(__name__)

_CHARS_PER_TOKEN = 4
_SINGLE_PASS_TOKEN_LIMIT = 4000
_CHUNK_TOKEN_TARGET = 3000

_SUMMARIZE_SYSTEM = (
    "You are an expert meeting analyst. You produce concise, well-structured "
    "meeting summaries. Always respond with valid JSON only -- no text outside the JSON object."
)

_SINGLE_PASS_PROMPT = """\
Summarize the following meeting transcript.

Meeting title: {title}

Transcript:
---
{transcript}
---

Respond with a JSON object containing exactly these fields:
{{
  "summary_text": "<2-4 paragraph summary of key discussion points>",
  "key_topics": ["<topic1>", "<topic2>", ...],
  "action_items": [
    {{"owner": "<person or 'Unassigned'>", "description": "<what needs to be done>", "due": "<deadline or null>"}}
  ],
  "decisions": ["<decision1>", "<decision2>", ...]
}}
"""

_CHUNK_SUMMARY_PROMPT = """\
Summarize this section of a meeting transcript.

Meeting title: {title}
Section {chunk_index} of {total_chunks}:
---
{chunk}
---

Respond with a JSON object:
{{
  "section_summary": "<summary of this section>",
  "key_topics": ["<topic>", ...],
  "action_items": [
    {{"owner": "<person or 'Unassigned'>", "description": "<task>", "due": "<deadline or null>"}}
  ],
  "decisions": ["<decision>", ...]
}}
"""

_LIVE_TICK_SYSTEM = (
    "You are a fast meeting note-taker. Update the running notes with anything "
    "important from the latest chunk. Always respond with valid JSON only."
)

_LIVE_TICK_PROMPT = """\
You are tracking a meeting in real time.

Meeting title: {title}
Running notes so far:
---
{running_notes}
---

Latest transcript chunk (last ~60 seconds):
---
{chunk}
---

Respond with a JSON object:
{{
  "running_notes_delta": ["<new bullet to add to running notes>", ...],
  "new_action_items": [
    {{"owner": "<person or 'Unassigned'>", "description": "<task>", "due": "<deadline or null>"}}
  ]
}}
Only include items that are NEW since the running notes — do not repeat existing bullets.
"""

_COMBINE_PROMPT = """\
Combine these section summaries into one cohesive meeting summary.

Meeting title: {title}

Section summaries:
---
{section_summaries}
---

Respond with a JSON object containing exactly these fields:
{{
  "summary_text": "<2-4 paragraph summary of key discussion points>",
  "key_topics": ["<topic1>", "<topic2>", ...],
  "action_items": [
    {{"owner": "<person or 'Unassigned'>", "description": "<what needs to be done>", "due": "<deadline or null>"}}
  ],
  "decisions": ["<decision1>", "<decision2>", ...]
}}
"""


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def _split_transcript(text: str, chunk_token_target: int = _CHUNK_TOKEN_TARGET) -> list[str]:
    char_target = chunk_token_target * _CHARS_PER_TOKEN
    if len(text) <= char_target:
        return [text]
    paragraphs = text.split("\n\n")
    if len(paragraphs) < 2:
        paragraphs = text.split("\n")
    chunks, current, current_len = [], [], 0
    for para in paragraphs:
        if current_len + len(para) > char_target and current:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _parse_json_response(raw: str) -> dict:
    """Parse JSON from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


class MeetingSummaryService:
    async def summarize(self, transcript_text: str, meeting_title: str = "") -> dict:
        if not transcript_text.strip():
            return {"summary_text": "", "key_topics": [], "action_items": [], "decisions": []}
        title = meeting_title or "Untitled Meeting"
        estimated_tokens = _estimate_tokens(transcript_text)
        logger.info("summarizing_meeting", title=title, estimated_tokens=estimated_tokens)
        if estimated_tokens <= _SINGLE_PASS_TOKEN_LIMIT:
            return await self._single_pass(transcript_text, title)
        return await self._map_reduce(transcript_text, title)

    async def _single_pass(self, transcript: str, title: str) -> dict:
        client = get_unified_llm_client()
        prompt = _SINGLE_PASS_PROMPT.format(title=title, transcript=transcript)
        raw = await client.chat(
            prompt, system=_SUMMARIZE_SYSTEM, temperature=0.1,
            task_type="summary",
        )
        result = _parse_json_response(raw)
        return self._normalize(result)

    async def _map_reduce(self, transcript: str, title: str) -> dict:
        client = get_unified_llm_client()
        chunks = _split_transcript(transcript)
        total = len(chunks)
        logger.info("map_reduce_summarization", chunks=total)
        section_summaries = []
        for i, chunk in enumerate(chunks, start=1):
            prompt = _CHUNK_SUMMARY_PROMPT.format(title=title, chunk_index=i, total_chunks=total, chunk=chunk)
            try:
                raw = await client.chat(
                    prompt, system=_SUMMARIZE_SYSTEM, temperature=0.1,
                    task_type="summary",
                )
                section_summaries.append(_parse_json_response(raw))
            except Exception as e:
                logger.warning("chunk_summarization_failed", chunk=i, error=str(e))
                section_summaries.append({"section_summary": f"[Section {i} failed]", "key_topics": [], "action_items": [], "decisions": []})
        combined = "\n\n".join(
            f"--- Section {i} ---\nSummary: {s.get('section_summary', '')}\nTopics: {', '.join(s.get('key_topics', []))}"
            for i, s in enumerate(section_summaries, start=1)
        )
        reduce_prompt = _COMBINE_PROMPT.format(title=title, section_summaries=combined)
        raw = await client.chat(
            reduce_prompt, system=_SUMMARIZE_SYSTEM, temperature=0.1,
            task_type="summary",
        )
        result = _parse_json_response(raw)
        return self._normalize(result)

    async def live_tick(
        self,
        chunk_text: str,
        running_notes: list[str],
        meeting_title: str = "",
    ) -> dict:
        """Lightweight running-notes update for in-progress meetings.

        Pulls a quick LLM call with the latest transcript chunk and the
        accumulated running notes. Returns delta-only output so the caller can
        append rather than re-render the world.
        """
        if not chunk_text.strip():
            return {"running_notes_delta": [], "new_action_items": []}
        client = get_unified_llm_client()
        notes_blob = "\n".join(f"- {n}" for n in running_notes[-20:]) or "(none yet)"
        prompt = _LIVE_TICK_PROMPT.format(
            title=meeting_title or "Untitled Meeting",
            running_notes=notes_blob,
            chunk=chunk_text,
        )
        try:
            raw = await client.chat(
                prompt, system=_LIVE_TICK_SYSTEM, temperature=0.2,
                task_type="summary",
            )
            data = _parse_json_response(raw)
        except Exception as e:  # noqa: BLE001
            logger.warning("live_tick_failed", error=str(e))
            return {"running_notes_delta": [], "new_action_items": []}
        return {
            "running_notes_delta": [str(x).strip() for x in data.get("running_notes_delta", []) if str(x).strip()],
            "new_action_items": list(data.get("new_action_items", [])),
        }

    @staticmethod
    def _normalize(result: dict) -> dict:
        return {
            "summary_text": result.get("summary_text", ""),
            "key_topics": list(result.get("key_topics", [])),
            "action_items": list(result.get("action_items", [])),
            "decisions": list(result.get("decisions", [])),
        }


_instance: MeetingSummaryService | None = None

def get_meeting_summary_service() -> MeetingSummaryService:
    global _instance
    if _instance is None:
        _instance = MeetingSummaryService()
    return _instance
