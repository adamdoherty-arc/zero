"""
Ambient vision tick — scheduled job that pulls a frame from the active
SightProvider, runs VLM scene description, and writes noteworthy
observations to the Obsidian vault under
`00_Meta/_agent/vision/{YYYY-MM-DD}/{HH-MM}.md`.

Design goals:
  - Skip cleanly when VLM / providers are unavailable (no spam in logs).
  - Never pile up — an asyncio.Lock guards against overlapping ticks
    when the VLM takes longer than the schedule interval.
  - Dedup boring scenes — we hash the first 20 chars of each caption
    and don't write the same one twice in a row.
  - Actionable frames also surface to the agent approval queue
    (best-effort; failures don't break the tick).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger()


_TICK_LOCK = asyncio.Lock()
_LAST_CAPTION_HASH: Optional[str] = None
_LAST_CAPTION_AT: float = 0.0
_DEDUP_WINDOW_S = 300.0  # 5 min — don't write the same caption twice inside this


def _caption_hash(caption: str) -> str:
    return hashlib.sha1(caption[:120].lower().encode("utf-8")).hexdigest()[:10]


async def ambient_vision_tick() -> dict:
    """
    One tick of the ambient vision loop. Intended to be scheduled every
    30 s from scheduler_service. Returns a small dict summarizing what it
    did for test / diagnostic purposes.
    """
    global _LAST_CAPTION_HASH, _LAST_CAPTION_AT

    if _TICK_LOCK.locked():
        logger.debug("ambient_vision_tick_skipped_busy")
        return {"status": "skipped_busy"}

    async with _TICK_LOCK:
        from app.services.sight import get_sight_registry
        from app.services.vision_vlm_service import get_vision_vlm_service

        reg = get_sight_registry()
        prov = reg.get_active()
        if prov is None:
            return {"status": "skipped_no_provider"}

        try:
            status = await prov.status()
        except Exception as e:
            logger.warning("ambient_vision_tick_status_failed", error=str(e)[:160])
            return {"status": "skipped_status_error", "error": str(e)[:160]}

        if not status.active:
            return {"status": "skipped_provider_idle", "provider": prov.name}

        # Skip if the most recent frame is stale — the provider might be
        # "active" but the camera / ingest stream is no longer fresh.
        if status.last_frame_ts and (time.time() - status.last_frame_ts) > 60.0:
            return {"status": "skipped_stale_frame", "provider": prov.name}

        jpeg = await prov.get_latest_frame()
        if not jpeg:
            return {"status": "skipped_no_frame", "provider": prov.name}

        vlm = get_vision_vlm_service()
        scene = await vlm.describe_scene(jpeg)
        caption = scene.get("caption", "").strip()
        if not caption:
            return {"status": "skipped_empty_vlm", "provider": prov.name}

        now = time.time()
        h = _caption_hash(caption)
        if h == _LAST_CAPTION_HASH and (now - _LAST_CAPTION_AT) < _DEDUP_WINDOW_S:
            return {"status": "skipped_duplicate", "caption": caption[:80]}
        _LAST_CAPTION_HASH = h
        _LAST_CAPTION_AT = now

        vault_result = _write_vault_entry(prov.name, scene)

        actionable = scene.get("actionable")
        approval_id: Optional[str] = None
        if actionable:
            try:
                approval_id = await _propose_approval(prov.name, scene)
            except Exception as e:
                logger.warning("ambient_vision_approval_failed", error=str(e)[:200])

        logger.info(
            "ambient_vision_observation",
            provider=prov.name,
            caption_preview=caption[:100],
            actionable=actionable,
            vault=vault_result,
            approval_id=approval_id,
        )
        return {
            "status": "ok",
            "provider": prov.name,
            "caption": caption,
            "actionable": actionable,
            "vault": vault_result,
            "approval_id": approval_id,
        }


def _write_vault_entry(provider_name: str, scene: dict) -> Optional[str]:
    try:
        from app.services.vault_writer_service import get_vault_writer
    except Exception as e:
        logger.debug("ambient_vision_no_vault_writer", error=str(e))
        return None

    now = datetime.now()
    rel_path = (
        f"00_Meta/_agent/vision/{now.strftime('%Y-%m-%d')}/"
        f"{now.strftime('%H-%M-%S')}-{provider_name}.md"
    )
    caption = scene.get("caption", "")
    actionable = scene.get("actionable") or "none"
    raw = scene.get("raw", "")
    body = (
        f"---\n"
        f"type: agent/vision-observation\n"
        f"provider: {provider_name}\n"
        f"model: {scene.get('model','')}\n"
        f"captured_at: {now.isoformat(timespec='seconds')}\n"
        f"actionable: {actionable}\n"
        f"---\n\n"
        f"## Observation\n\n{caption}\n\n"
        f"### Raw VLM output\n\n```\n{raw}\n```\n"
    )
    try:
        writer = get_vault_writer()
        writer.write_agent_file(rel_path, body, source="ambient_vision")
        return rel_path
    except Exception as e:
        logger.warning("ambient_vision_vault_write_failed", error=str(e)[:200])
        return None


async def _propose_approval(provider_name: str, scene: dict) -> Optional[str]:
    """
    Push the actionable observation into the agent approval queue. Import
    lazily so a missing queue doesn't break the tick.
    """
    try:
        from app.services.agent_approval_service import get_agent_approval_service
    except Exception:
        return None

    caption = scene.get("caption", "")
    actionable = scene.get("actionable") or ""
    summary = f"Vision ({provider_name}): {actionable} — {caption[:120]}"
    try:
        svc = get_agent_approval_service()
        approval = await svc.submit(
            kind="vision_observation",
            summary=summary,
            payload={
                "provider": provider_name,
                "caption": caption,
                "actionable": actionable,
                "model": scene.get("model"),
            },
        )
        return getattr(approval, "id", None) or approval.get("id") if isinstance(approval, dict) else None
    except Exception as e:
        logger.debug("ambient_vision_approval_skip", error=str(e)[:160])
        return None
