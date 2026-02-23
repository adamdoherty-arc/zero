"""
Continuous Enhancement Engine for ZERO.

Runs every 10 minutes via scheduler. Scans Zero and Legion codebases for
improvement signals, uses Ollama to evaluate them, queues actionable fixes
to the task executor, and batches completed improvements into Legion sprints.

Pipeline: Scan → Analyze (Ollama) → Queue → Execute → Sprint-Batch → Log
"""

import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

import structlog

from app.infrastructure.config import get_settings, get_workspace_path
from app.infrastructure.storage import JsonStorage

logger = structlog.get_logger(__name__)

DEFAULT_CONFIG = {
    "enabled": True,
    "cycle_interval_minutes": 10,
    "max_improvements_per_cycle": 3,
    "max_improvements_per_hour": 10,
    "max_improvements_per_day": 50,
    "target_projects": ["zero", "legion"],
    "auto_sprint_batch_threshold": 10,
    "cooldown_after_failure_minutes": 30,
    "analysis_model": None,  # resolved via LLM router (task_type=analysis)
}


class ContinuousEnhancementService:
    """
    Core 24/7 enhancement engine. Called every 10 minutes by the scheduler.
    Orchestrates scan → analyze → queue → sprint-batch → log.
    """

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("engine"))
        self._state_file = "engine_state.json"
        self._config_file = "engine_config.json"
        self._lock = asyncio.Lock()
        self._running = False
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)

    async def _load_config(self):
        """Load engine config from storage, merging with defaults."""
        data = await self._storage.read(self._config_file)
        if data:
            for key in DEFAULT_CONFIG:
                if key in data:
                    self._config[key] = data[key]

    async def _save_config(self):
        """Persist engine config."""
        await self._storage.write(self._config_file, self._config)

    async def _load_state(self) -> Dict[str, Any]:
        """Load engine state (cycle counts, timestamps, cooldown)."""
        data = await self._storage.read(self._state_file)
        if not data:
            data = {
                "cycle_count": 0,
                "improvements_today": 0,
                "improvements_this_hour": 0,
                "last_cycle_at": None,
                "last_improvement_at": None,
                "cooldown_until": None,
                "today_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "hour_marker": datetime.utcnow().strftime("%Y-%m-%d-%H"),
                "queued_total": 0,
                "completed_total": 0,
                "failed_total": 0,
            }
        return data

    async def _save_state(self, state: Dict[str, Any]):
        """Persist engine state."""
        await self._storage.write(self._state_file, state)

    # ========================================
    # PUBLIC API
    # ========================================

    async def get_status(self) -> Dict[str, Any]:
        """Get engine status for API and frontend."""
        await self._load_config()
        state = await self._load_state()

        return {
            "enabled": self._config["enabled"],
            "running": self._running,
            "cycle_count": state.get("cycle_count", 0),
            "improvements_today": state.get("improvements_today", 0),
            "improvements_this_hour": state.get("improvements_this_hour", 0),
            "queued_total": state.get("queued_total", 0),
            "completed_total": state.get("completed_total", 0),
            "failed_total": state.get("failed_total", 0),
            "last_cycle_at": state.get("last_cycle_at"),
            "last_improvement_at": state.get("last_improvement_at"),
            "cooldown_until": state.get("cooldown_until"),
            "target_projects": self._config["target_projects"],
            "config": self._config,
        }

    async def set_enabled(self, enabled: bool):
        """Toggle engine on/off."""
        await self._load_config()
        self._config["enabled"] = enabled
        await self._save_config()
        logger.info("engine_toggled", enabled=enabled)

    async def update_config(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update engine config (partial)."""
        await self._load_config()
        for key, value in updates.items():
            if key in DEFAULT_CONFIG:
                self._config[key] = value
        await self._save_config()
        return self._config

    async def get_config(self) -> Dict[str, Any]:
        """Get current engine config."""
        await self._load_config()
        return dict(self._config)

    # ========================================
    # MAIN CYCLE (called by scheduler)
    # ========================================

    async def run_cycle(self):
        """
        Main entry point. Called every 10 minutes by the scheduler.
        Orchestrates: check limits → scan → analyze → queue → sprint-batch → log.
        """
        from app.services.activity_log_service import get_activity_log_service

        activity_log = get_activity_log_service()

        await self._load_config()

        if not self._config["enabled"]:
            return

        if self._running:
            logger.info("engine_cycle_skip", reason="already_running")
            return

        self._running = True
        state = await self._load_state()

        try:
            # Reset daily/hourly counters if needed
            state = self._reset_counters(state)

            # Check cooldown
            if state.get("cooldown_until"):
                cooldown_until = datetime.fromisoformat(state["cooldown_until"])
                if datetime.utcnow() < cooldown_until:
                    logger.info("engine_cycle_skip", reason="cooldown",
                                cooldown_until=state["cooldown_until"])
                    return
                state["cooldown_until"] = None

            # Check rate limits
            if state.get("improvements_today", 0) >= self._config["max_improvements_per_day"]:
                logger.info("engine_cycle_skip", reason="daily_limit_reached")
                return
            if state.get("improvements_this_hour", 0) >= self._config["max_improvements_per_hour"]:
                logger.info("engine_cycle_skip", reason="hourly_limit_reached")
                return

            state["cycle_count"] = state.get("cycle_count", 0) + 1
            state["last_cycle_at"] = datetime.utcnow().isoformat() + "Z"

            await activity_log.log_event(
                "cycle_start", "engine", f"Enhancement cycle #{state['cycle_count']}",
                details={"cycle": state["cycle_count"]}, source="engine",
            )

            # Phase 1: Scan for new signals
            scan_result = await self._scan_phase()
            new_signals = scan_result.get("new_signals", 0) if scan_result else 0

            if new_signals > 0:
                await activity_log.log_event(
                    "scan", "engine",
                    f"Found {new_signals} new signals across projects",
                    details=scan_result, source="engine",
                )

            # Phase 2: Get pending signals (both new AND previously-found unprocessed ones)
            signals = await self._get_pending_signals()

            if not signals:
                await activity_log.log_event(
                    "scan", "engine", "No signals to process (no new or pending)",
                    details=scan_result or {}, source="engine",
                )
                await self._save_state(state)
                return

            analyzed = await self._analyze_phase(signals)

            if not analyzed:
                await activity_log.log_event(
                    "scan", "engine",
                    f"Analyzed {len(signals)} signals, none actionable",
                    details={"signals_checked": len(signals)}, source="engine",
                )
                await self._save_state(state)
                return

            # Phase 3: Queue actionable improvements
            queued_count = await self._queue_phase(analyzed, state)
            state["queued_total"] = state.get("queued_total", 0) + queued_count

            # Phase 4: Check if we should batch into a sprint
            await self._sprint_batch_phase(state)

            await self._save_state(state)

            await activity_log.log_event(
                "cycle_complete", "engine",
                f"Cycle #{state['cycle_count']} complete: {queued_count} improvements queued",
                details={"queued": queued_count, "signals_analyzed": len(analyzed)},
                source="engine",
            )

        except Exception as e:
            logger.error("engine_cycle_error", error=str(e))
            # Enter cooldown on failure
            cooldown_minutes = self._config["cooldown_after_failure_minutes"]
            state["cooldown_until"] = (
                datetime.utcnow() + timedelta(minutes=cooldown_minutes)
            ).isoformat()
            state["failed_total"] = state.get("failed_total", 0) + 1
            await self._save_state(state)

            await activity_log.log_event(
                "cycle_error", "engine", f"Cycle error: {str(e)[:200]}",
                details={"error": str(e)}, source="engine", status="error",
            )
        finally:
            self._running = False

    # ========================================
    # PHASE 1: SCAN
    # ========================================

    async def _scan_phase(self) -> Optional[Dict[str, Any]]:
        """Scan target projects for enhancement signals."""
        from app.services.enhancement_service import get_enhancement_service

        enhancement = get_enhancement_service()
        try:
            result = await enhancement.scan_all_projects()
            logger.info("engine_scan_complete",
                        signals=result.get("signals_found", 0),
                        new=result.get("new_signals", 0))
            return result
        except Exception as e:
            logger.error("engine_scan_error", error=str(e))
            return None

    # ========================================
    # PHASE 2: ANALYZE (Ollama)
    # ========================================

    async def _get_pending_signals(self) -> List[Dict[str, Any]]:
        """Get pending signals from PostgreSQL, filtered to target projects."""
        from sqlalchemy import select
        from app.infrastructure.database import get_session
        from app.db.models import EnhancementSignalModel

        target = set(self._config["target_projects"])

        async with get_session() as session:
            query = (
                select(EnhancementSignalModel)
                .where(EnhancementSignalModel.status == "pending")
                .order_by(EnhancementSignalModel.detected_at.desc())
                .limit(self._config["max_improvements_per_cycle"] * 3)
            )
            result = await session.execute(query)
            rows = result.scalars().all()

        # Filter to target projects and convert to dicts
        pending = []
        for r in rows:
            project_name = None
            if r.source_file:
                # Extract project name from path like /projects/zero/...
                parts = r.source_file.replace("\\", "/").split("/")
                for i, part in enumerate(parts):
                    if part == "projects" and i + 1 < len(parts):
                        project_name = parts[i + 1]
                        break
            if project_name and project_name not in target:
                continue
            pending.append({
                "id": r.id,
                "type": r.type,
                "severity": r.severity,
                "message": r.message,
                "source_file": r.source_file,
                "line_number": r.line_number,
                "status": r.status,
                "project_name": project_name or "zero",
                "context": r.context or "",
                "priority_score": 50,  # Default score
            })

        return pending

    async def _analyze_phase(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use Ollama to evaluate each signal: is it actionable? What's the fix?"""
        if not signals:
            return []

        analyzed = []
        for signal in signals:
            try:
                evaluation = await self._evaluate_signal(signal)
                if evaluation and evaluation.get("actionable"):
                    analyzed.append({
                        **signal,
                        "evaluation": evaluation,
                    })
            except Exception as e:
                logger.warning("signal_analysis_failed",
                               signal_id=signal.get("id"),
                               error=str(e))

            # Don't overwhelm Ollama
            await asyncio.sleep(1)

        logger.info("engine_analyze_complete",
                     evaluated=len(signals), actionable=len(analyzed))
        return analyzed

    async def _evaluate_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Ask Ollama to evaluate a single signal."""
        import json

        prompt = f"""You are a code improvement assistant. Evaluate this enhancement signal and decide if it's actionable.

Signal type: {signal.get('type')}
Severity: {signal.get('severity')}
Message: {signal.get('message')}
File: {signal.get('source_file')}
Line: {signal.get('line_number')}
Project: {signal.get('project_name')}
Context:
```
{signal.get('context', 'N/A')}
```

Respond with JSON only (no markdown, no explanation):
{{
    "actionable": true/false,
    "confidence": 0-100,
    "risk": 0-100,
    "fix_description": "Brief description of the fix",
    "fix_title": "Short title for the improvement task",
    "estimated_files": 1
}}

Rules:
- Only mark actionable if the fix is clear and low-risk
- Risk > 50 means skip it (too dangerous for auto-fix)
- Be conservative — prefer false negatives to breaking code"""

        response_text = await self._call_ollama(prompt)
        if not response_text:
            return None

        # Parse JSON from response (handle thinking model output)
        try:
            # Strip any <think>...</think> tags if present
            import re
            cleaned = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
            # Find JSON object in response
            json_match = re.search(r'\{[^{}]*\}', cleaned, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            logger.warning("signal_eval_parse_fail", response=response_text[:200])

        return None

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama for analysis using shared client."""
        from app.infrastructure.ollama_client import get_ollama_client

        client = get_ollama_client()
        model = self._config.get("analysis_model")  # explicit override or None
        timeout = self._config.get("ollama_timeout", 300)

        return await client.chat_safe(
            prompt,
            model=model,
            task_type="analysis",
            temperature=0.1,
            num_predict=500,
            timeout=timeout,
            max_retries=2,
        )

    # ========================================
    # PHASE 3: QUEUE
    # ========================================

    async def _queue_phase(
        self, analyzed: List[Dict[str, Any]], state: Dict[str, Any]
    ) -> int:
        """Score and queue top improvements for execution."""
        from app.services.task_execution_service import get_task_execution_service
        from app.services.activity_log_service import get_activity_log_service
        from app.services.enhancement_service import get_enhancement_service

        executor = get_task_execution_service()
        activity_log = get_activity_log_service()
        enhancement = get_enhancement_service()

        # Score and rank
        scored = []
        for item in analyzed:
            ev = item.get("evaluation", {})
            score = (
                ev.get("confidence", 50) * 0.3
                + (100 - ev.get("risk", 50)) * 0.3
                + item.get("impact_score", 50) * 0.2
                + item.get("confidence", 50) * 0.2
            )
            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Respect per-cycle limit
        max_this_cycle = min(
            self._config["max_improvements_per_cycle"],
            self._config["max_improvements_per_day"] - state.get("improvements_today", 0),
            self._config["max_improvements_per_hour"] - state.get("improvements_this_hour", 0),
        )

        queued = 0
        settings = get_settings()

        for _score, item in scored[:max_this_cycle]:
            ev = item.get("evaluation", {})
            project_name = item.get("project_name", "zero")
            project_path = f"{settings.projects_root}/{project_name}"

            title = ev.get("fix_title", item.get("message", "Enhancement")[:80])
            description = (
                f"Auto-detected {item.get('type', 'enhancement')} signal.\n\n"
                f"File: {item.get('source_file', 'unknown')}\n"
                f"Line: {item.get('line_number', '?')}\n"
                f"Signal: {item.get('message', '')}\n\n"
                f"Fix: {ev.get('fix_description', 'Address the identified issue')}\n\n"
                f"Context:\n```\n{item.get('context', '')}\n```"
            )

            try:
                task = await executor.submit_task(
                    title=f"[{project_name}] {title}",
                    description=description,
                    project_path=project_path,
                    priority="medium",
                )

                # Mark signal as converted
                await self._mark_signal_converted(
                    enhancement, item.get("id"), task.get("task_id")
                )

                await activity_log.log_event(
                    "queue", project_name,
                    f"Queued: {title}",
                    details={
                        "task_id": task.get("task_id"),
                        "signal_id": item.get("id"),
                        "file": item.get("source_file"),
                    },
                    source="engine",
                )

                queued += 1
                state["improvements_today"] = state.get("improvements_today", 0) + 1
                state["improvements_this_hour"] = state.get("improvements_this_hour", 0) + 1

            except Exception as e:
                logger.error("engine_queue_error",
                             signal_id=item.get("id"), error=str(e))

        logger.info("engine_queue_complete", queued=queued)
        return queued

    async def _mark_signal_converted(
        self, enhancement, signal_id: str, task_id: str
    ):
        """Mark a signal as converted (submitted for execution) in PostgreSQL."""
        from app.infrastructure.database import get_session
        from app.db.models import EnhancementSignalModel

        async with get_session() as session:
            signal = await session.get(EnhancementSignalModel, signal_id)
            if signal:
                signal.status = "converted"
                signal.converted_to_task = task_id
                signal.converted_at = datetime.utcnow()

    # ========================================
    # PHASE 4: SPRINT BATCHING
    # ========================================

    async def _sprint_batch_phase(self, state: Dict[str, Any]):
        """
        When enough improvements complete for a project, batch them
        into a Legion sprint.
        """
        from app.services.task_execution_service import get_task_execution_service
        from app.services.legion_client import get_legion_client
        from app.services.activity_log_service import get_activity_log_service
        from app.services.enhancement_service import SCAN_PROJECTS

        executor = get_task_execution_service()
        activity_log = get_activity_log_service()

        # Get completed tasks from history
        history_data = await executor._storage.read("history.json")
        all_tasks = history_data.get("tasks", [])

        # Find completed engine tasks not yet batched into a sprint
        unbatched = [
            t for t in all_tasks
            if t.get("result") == "success"
            and not t.get("sprint_batched")
            and t.get("title", "").startswith("[")
        ]

        # Group by project
        by_project: Dict[str, List[Dict]] = {}
        for task in unbatched:
            # Extract project name from title like "[zero] Fix something"
            title = task.get("title", "")
            if title.startswith("[") and "]" in title:
                project = title[1:title.index("]")]
                by_project.setdefault(project, []).append(task)

        threshold = self._config["auto_sprint_batch_threshold"]

        for project_name, tasks in by_project.items():
            if len(tasks) < threshold:
                continue

            # Get Legion project ID
            project_config = SCAN_PROJECTS.get(project_name)
            if not project_config:
                continue

            legion_id = project_config["legion_id"]
            today = datetime.utcnow().strftime("%Y-%m-%d")

            try:
                client = get_legion_client()
                sprint = await client.create_sprint({
                    "name": f"Auto-Enhancement {project_name.title()} {today}",
                    "project_id": legion_id,
                    "status": "active",
                    "description": (
                        f"Automatically created sprint with {len(tasks)} "
                        f"improvements for {project_name}."
                    ),
                })

                sprint_id = sprint.get("id")
                if not sprint_id:
                    continue

                # Create tasks in the sprint
                for task in tasks:
                    try:
                        await client.create_task(sprint_id, {
                            "title": task.get("title", "Enhancement"),
                            "description": task.get("description", "")[:500],
                            "status": "done",
                            "priority": "medium",
                        })
                    except Exception:
                        pass  # Best-effort

                # Mark tasks as batched in history
                for task in tasks:
                    task["sprint_batched"] = True
                    task["sprint_id"] = sprint_id
                await executor._storage.write("history.json", {"tasks": all_tasks})

                state["completed_total"] = state.get("completed_total", 0) + len(tasks)

                await activity_log.log_event(
                    "sprint_created", project_name,
                    f"Sprint created: {len(tasks)} improvements for {project_name}",
                    details={
                        "sprint_id": sprint_id,
                        "task_count": len(tasks),
                        "sprint_name": f"Auto-Enhancement {project_name.title()} {today}",
                    },
                    source="engine", status="success",
                )

                logger.info("engine_sprint_created",
                            project=project_name, sprint_id=sprint_id,
                            task_count=len(tasks))

            except Exception as e:
                logger.error("engine_sprint_batch_error",
                             project=project_name, error=str(e))

    # ========================================
    # HELPERS
    # ========================================

    def _reset_counters(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Reset daily/hourly counters when the period changes."""
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")
        hour = now.strftime("%Y-%m-%d-%H")

        if state.get("today_date") != today:
            state["today_date"] = today
            state["improvements_today"] = 0

        if state.get("hour_marker") != hour:
            state["hour_marker"] = hour
            state["improvements_this_hour"] = 0

        return state


@lru_cache()
def get_continuous_enhancement_service() -> ContinuousEnhancementService:
    return ContinuousEnhancementService()
