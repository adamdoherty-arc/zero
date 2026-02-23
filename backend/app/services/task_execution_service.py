"""
Autonomous Task Execution Service for ZERO.

Takes a task, uses Ollama to plan implementation, generates code,
writes files, validates, and reports progress. The core engine that
makes Zero work autonomously.

Pipeline: Submit → Plan → Execute Steps → Validate → Notify → Next Task
"""

import asyncio
import ast
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
import structlog

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_workspace_path, get_settings

logger = structlog.get_logger(__name__)


class ExecutionStatus(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    VALIDATING = "validating"
    COMPLETE = "complete"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ExecutionStep:
    """A single step in a task execution plan."""
    step_num: int
    action: str  # create_file, modify_file, delete_file
    file_path: str
    description: str
    instructions: str
    status: str = "pending"  # pending, running, success, failed, skipped
    result_message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step_num,
            "action": self.action,
            "file": self.file_path,
            "description": self.description,
            "instructions": self.instructions,
            "status": self.status,
            "result_message": self.result_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class TaskExecutionService:
    """
    Autonomous task execution engine.

    Picks up tasks, decomposes them into steps using Ollama,
    executes each step (generate code, write files, validate),
    and reports progress through notifications.
    """

    def __init__(self):
        self._storage = JsonStorage(get_workspace_path("agent"))
        self._current_task: Optional[Dict[str, Any]] = None
        self._steps: List[ExecutionStep] = []
        self._status = ExecutionStatus.IDLE
        self._should_stop = False
        self._paused = False
        self._lock = asyncio.Lock()

        # Configurable settings (loaded from workspace/agent/settings.json)
        self._settings = {
            "max_files_per_task": 10,
            "max_lines_per_file": 200,
            "max_ollama_retries": 2,
            "ollama_timeout": 120,
            "protected_paths": [
                "infrastructure/", "migrations/", ".env",
                "docker-compose", "Dockerfile", ".lock",
            ],
            "coding_model": None,  # resolved via LLM router (task_type=coding)
        }

    async def _load_settings(self):
        """Load execution settings from storage."""
        data = await self._storage.read("settings.json")
        if data:
            self._settings.update(data)

    async def _save_settings(self):
        """Save execution settings."""
        await self._storage.write("settings.json", self._settings)

    def get_settings(self) -> Dict[str, Any]:
        return dict(self._settings)

    async def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        await self._load_settings()
        for key in updates:
            if key in self._settings:
                self._settings[key] = updates[key]
        await self._save_settings()
        return self._settings

    # ========================================
    # STATUS & CONTROL
    # ========================================

    def get_status(self) -> Dict[str, Any]:
        """Get current execution status."""
        result = {
            "running": self._status not in (ExecutionStatus.IDLE, ExecutionStatus.STOPPED),
            "paused": self._paused,
            "status": self._status.value,
            "current_task": None,
            "queue_depth": 0,
            "completed_today": 0,
        }

        if self._current_task:
            current_step = 0
            total_steps = len(self._steps)
            current_file = ""

            for step in self._steps:
                if step.status == "running":
                    current_step = step.step_num
                    current_file = step.file_path
                    break
                elif step.status in ("success", "failed", "skipped"):
                    current_step = step.step_num

            completed_steps = sum(1 for s in self._steps if s.status in ("success", "skipped"))
            progress = int((completed_steps / total_steps * 100)) if total_steps > 0 else 0

            result["current_task"] = {
                "task_id": self._current_task.get("task_id"),
                "title": self._current_task.get("title"),
                "description": self._current_task.get("description", "")[:200],
                "status": self._status.value,
                "current_step": current_step,
                "total_steps": total_steps,
                "current_file": current_file,
                "started_at": self._current_task.get("started_at"),
                "progress_percent": progress,
                "log": [s.to_dict() for s in self._steps],
            }

        return result

    def stop(self):
        """Signal the executor to stop after the current step."""
        self._should_stop = True
        logger.info("task_execution_stop_requested")

    def pause(self):
        """Pause the worker loop."""
        self._paused = True
        logger.info("task_execution_paused")

    def resume(self):
        """Resume the worker loop."""
        self._paused = False
        logger.info("task_execution_resumed")

    def is_busy(self) -> bool:
        return self._status not in (ExecutionStatus.IDLE, ExecutionStatus.COMPLETE,
                                     ExecutionStatus.FAILED, ExecutionStatus.STOPPED)

    # ========================================
    # TASK SUBMISSION
    # ========================================

    async def submit_task(
        self,
        title: str,
        description: str,
        project_path: Optional[str] = None,
        priority: str = "medium",
    ) -> Dict[str, Any]:
        """Submit a task for autonomous execution."""
        task_id = f"agent-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()

        task = {
            "task_id": task_id,
            "title": title,
            "description": description,
            "project_path": project_path,
            "priority": priority,
            "status": "queued",
            "submitted_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
        }

        # Add to queue
        queue_data = await self._storage.read("queue.json")
        queue = queue_data.get("tasks", [])
        queue.append(task)
        await self._storage.write("queue.json", {"tasks": queue})

        logger.info("task_submitted", task_id=task_id, title=title)

        # Send notification
        await self._notify(f"Task Queued: {title}", f"Task {task_id} added to execution queue.")

        return task

    async def get_queue(self) -> List[Dict[str, Any]]:
        """Get queued tasks."""
        data = await self._storage.read("queue.json")
        return [t for t in data.get("tasks", []) if t.get("status") == "queued"]

    async def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get completed task history."""
        data = await self._storage.read("history.json")
        history = data.get("tasks", [])
        return history[-limit:]

    async def get_task_log(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get execution log for a specific task."""
        # Check current task
        if self._current_task and self._current_task.get("task_id") == task_id:
            return {
                "task_id": task_id,
                "status": self._status.value,
                "steps": [s.to_dict() for s in self._steps],
            }

        # Check history
        data = await self._storage.read("history.json")
        for task in data.get("tasks", []):
            if task.get("task_id") == task_id:
                return task

        return None

    # ========================================
    # WORKER LOOP (called by scheduler)
    # ========================================

    async def check_and_execute(self):
        """
        Called by the scheduler every 2 minutes.
        If idle and there are queued tasks, pick one and execute it.
        """
        if self._paused:
            return

        if self.is_busy():
            return

        async with self._lock:
            # Get next queued task
            queue_data = await self._storage.read("queue.json")
            queue = queue_data.get("tasks", [])
            queued = [t for t in queue if t.get("status") == "queued"]

            if not queued:
                return

            # Sort by priority
            priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            queued.sort(key=lambda t: priority_order.get(t.get("priority", "medium"), 2))

            # Pick the top task
            task = queued[0]
            task["status"] = "running"

            # Update queue
            await self._storage.write("queue.json", {"tasks": queue})

            # Execute
            await self.execute_task(task)

    async def execute_task(self, task: Dict[str, Any]):
        """Execute a single task end-to-end."""
        task_id = task.get("task_id", "unknown")
        title = task.get("title", "Untitled")

        logger.info("task_execution_start", task_id=task_id, title=title)
        self._current_task = task
        self._current_task["started_at"] = datetime.utcnow().isoformat()
        self._steps = []
        self._should_stop = False

        # Log execution start
        try:
            from app.services.activity_log_service import get_activity_log_service
            activity_log = get_activity_log_service()
            project = self._extract_project_name(title)
            await activity_log.log_event(
                "execute_start", project, f"Started: {title}",
                details={"task_id": task_id}, source="task_executor",
            )
        except Exception:
            pass

        await self._notify(f"Started: {title}", f"Zero is now working on: {task.get('description', '')[:200]}")
        await self._save_current_state()

        try:
            # Phase 1: Plan
            self._status = ExecutionStatus.PLANNING
            await self._save_current_state()

            steps = await self._plan_task(task)
            if not steps:
                raise Exception("Planning failed — no steps generated")

            self._steps = steps
            await self._save_current_state()

            await self._notify(
                f"Plan Ready: {title}",
                f"Generated {len(steps)} steps: {', '.join(s.description[:40] for s in steps[:5])}"
            )

            # Phase 2: Execute each step
            self._status = ExecutionStatus.EXECUTING
            files_modified = 0

            for step in self._steps:
                if self._should_stop:
                    step.status = "skipped"
                    self._status = ExecutionStatus.STOPPED
                    await self._notify(f"Stopped: {title}", "Execution stopped by user.")
                    break

                step.status = "running"
                step.started_at = datetime.utcnow().isoformat()
                await self._save_current_state()

                await self._notify(
                    f"Step {step.step_num}/{len(self._steps)}",
                    f"{step.description} — {step.file_path}"
                )

                try:
                    result = await self._execute_step(step, task)
                    step.status = "success"
                    step.result_message = result.get("message", "Done")
                    if result.get("file_written"):
                        files_modified += 1
                except Exception as e:
                    step.status = "failed"
                    step.result_message = str(e)
                    logger.error("step_failed", step=step.step_num, error=str(e))

                step.completed_at = datetime.utcnow().isoformat()
                await self._save_current_state()

            # Phase 3: Complete
            if self._status != ExecutionStatus.STOPPED:
                self._status = ExecutionStatus.COMPLETE

            completed_steps = sum(1 for s in self._steps if s.status == "success")
            failed_steps = sum(1 for s in self._steps if s.status == "failed")

            result_summary = {
                "total_steps": len(self._steps),
                "completed": completed_steps,
                "failed": failed_steps,
                "files_modified": files_modified,
                "duration_seconds": self._calc_duration(),
            }

            task["status"] = "complete" if failed_steps == 0 else "partial"
            task["completed_at"] = datetime.utcnow().isoformat()
            task["result"] = result_summary
            task["execution_log"] = [s.to_dict() for s in self._steps]

            await self._notify(
                f"Complete: {title}",
                f"{completed_steps}/{len(self._steps)} steps done, {files_modified} files modified"
            )

        except Exception as e:
            self._status = ExecutionStatus.FAILED
            task["status"] = "failed"
            task["completed_at"] = datetime.utcnow().isoformat()
            task["result"] = {"error": str(e)}
            task["execution_log"] = [s.to_dict() for s in self._steps]

            await self._notify(f"Failed: {title}", f"Error: {str(e)[:200]}")
            logger.error("task_execution_failed", task_id=task_id, error=str(e))

        finally:
            # Log execution result
            try:
                from app.services.activity_log_service import get_activity_log_service
                activity_log = get_activity_log_service()
                project = self._extract_project_name(title)
                is_success = task.get("result") != "failed" and task.get("status") != "failed"
                event_type = "execute_complete" if is_success else "execute_fail"
                await activity_log.log_event(
                    event_type, project, f"{'Completed' if is_success else 'Failed'}: {title}",
                    details={
                        "task_id": task_id,
                        "result": task.get("result"),
                        "file_written": bool(task.get("result", {}).get("files_modified")),
                    },
                    source="task_executor",
                    status="success" if is_success else "error",
                )
            except Exception:
                pass

            # Move to history
            await self._move_to_history(task)
            # Remove from queue
            await self._remove_from_queue(task_id)
            # Clear current state
            self._current_task = None
            self._steps = []
            self._status = ExecutionStatus.IDLE
            await self._save_current_state()

    # ========================================
    # PLANNING (LLM-powered task decomposition)
    # ========================================

    async def _plan_task(self, task: Dict[str, Any]) -> List[ExecutionStep]:
        """Use Ollama to decompose a task into executable steps."""
        title = task.get("title", "")
        description = task.get("description", "")
        project_path = task.get("project_path")

        # Gather project context if available
        project_context = ""
        if project_path:
            project_context = await self._get_project_tree(project_path)

        prompt = f"""You are an autonomous coding agent. Break down this task into concrete implementation steps.

TASK: {title}
DESCRIPTION: {description}

{f"PROJECT FILE TREE:{chr(10)}{project_context}" if project_context else "No project context available — create files relative to the current directory."}

Return a JSON array of steps. Each step must have:
- "action": one of "create_file", "modify_file"
- "file_path": the file path to create or modify
- "description": short description of what this step does
- "instructions": detailed instructions for the code to write/change

Rules:
- Keep it practical — 3-8 steps maximum
- Each step should produce working code
- Use relative file paths from the project root
- For modify_file, describe what section to change and how
- Order steps logically (create dependencies first)

Return ONLY valid JSON array, no markdown fences, no explanation.
Example: [{{"action":"create_file","file_path":"src/hello.py","description":"Create hello module","instructions":"Create a Python module with a hello() function that returns 'Hello World'"}}]"""

        response = await self._call_ollama(prompt)
        if not response:
            return []

        steps = self._parse_plan_response(response)
        return steps

    def _parse_plan_response(self, response: str) -> List[ExecutionStep]:
        """Parse LLM response into execution steps."""
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Try to extract JSON array
        try:
            # Find the JSON array in the response
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
            else:
                data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("plan_parse_failed", response=text[:500])
            return []

        if not isinstance(data, list):
            return []

        steps = []
        max_files = self._settings.get("max_files_per_task", 10)

        for i, item in enumerate(data[:max_files]):
            if not isinstance(item, dict):
                continue

            step = ExecutionStep(
                step_num=i + 1,
                action=item.get("action", "create_file"),
                file_path=item.get("file_path", ""),
                description=item.get("description", ""),
                instructions=item.get("instructions", ""),
            )
            steps.append(step)

        return steps

    # ========================================
    # STEP EXECUTION
    # ========================================

    async def _execute_step(self, step: ExecutionStep, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single step: generate code and write it."""
        file_path = step.file_path
        project_path = task.get("project_path", "")

        # Safety: check protected paths
        for pattern in self._settings.get("protected_paths", []):
            if pattern in file_path:
                return {"message": f"Skipped — protected path: {pattern}", "file_written": False}

        # Resolve full path
        if project_path:
            full_path = Path(project_path) / file_path
        else:
            full_path = Path(file_path)

        if step.action == "create_file":
            return await self._create_file(full_path, step)
        elif step.action == "modify_file":
            return await self._modify_file(full_path, step)
        else:
            return {"message": f"Unknown action: {step.action}", "file_written": False}

    async def _create_file(self, full_path: Path, step: ExecutionStep) -> Dict[str, Any]:
        """Generate and write a new file."""
        prompt = f"""Write the complete code for this file.

FILE: {step.file_path}
PURPOSE: {step.description}
INSTRUCTIONS: {step.instructions}

Rules:
- Return ONLY the file contents, no markdown fences, no explanation
- Write production-quality code with proper imports
- Follow standard conventions for the file type
- Include brief docstrings/comments where helpful"""

        code = await self._call_ollama(prompt)
        if not code:
            raise Exception("LLM returned empty response")

        code = self._clean_code_response(code)

        # Validate if applicable
        self._validate_code(code, str(full_path))

        # Check line count
        max_lines = self._settings.get("max_lines_per_file", 200)
        line_count = len(code.split("\n"))
        if line_count > max_lines:
            raise Exception(f"Generated code too long ({line_count} lines, max {max_lines})")

        # Create parent directories
        await asyncio.to_thread(full_path.parent.mkdir, parents=True, exist_ok=True)

        # Write file
        await asyncio.to_thread(full_path.write_text, code, encoding="utf-8")

        logger.info("file_created", path=str(full_path), lines=line_count)
        return {"message": f"Created {step.file_path} ({line_count} lines)", "file_written": True}

    async def _modify_file(self, full_path: Path, step: ExecutionStep) -> Dict[str, Any]:
        """Read, modify, and write an existing file."""
        if not full_path.exists():
            # If file doesn't exist, treat as create
            return await self._create_file(full_path, step)

        # Read existing content
        original = await asyncio.to_thread(full_path.read_text, encoding="utf-8")

        prompt = f"""Modify this existing file according to the instructions.

FILE: {step.file_path}
INSTRUCTIONS: {step.instructions}

CURRENT FILE CONTENTS:
{original[:8000]}

Rules:
- Return the COMPLETE modified file contents
- No markdown fences, no explanation
- Make minimal changes — only what the instructions require
- Preserve existing code style, imports, and structure
- Keep all existing functionality intact"""

        modified = await self._call_ollama(prompt)
        if not modified:
            raise Exception("LLM returned empty response")

        modified = self._clean_code_response(modified)

        # Validate
        self._validate_code(modified, str(full_path))

        # Check diff size
        max_lines = self._settings.get("max_lines_per_file", 200)
        original_lines = len(original.split("\n"))
        modified_lines = len(modified.split("\n"))
        diff = abs(modified_lines - original_lines)
        if diff > max_lines:
            raise Exception(f"Modification too large ({diff} lines changed, max {max_lines})")

        # Create backup
        backup_path = full_path.with_suffix(full_path.suffix + ".bak")
        try:
            await asyncio.to_thread(backup_path.write_text, original, encoding="utf-8")
        except Exception:
            pass  # Non-critical

        # Write modified file
        await asyncio.to_thread(full_path.write_text, modified, encoding="utf-8")

        logger.info("file_modified", path=str(full_path), diff_lines=diff)
        return {
            "message": f"Modified {step.file_path} ({diff} lines changed)",
            "file_written": True,
            "backup": str(backup_path),
        }

    # ========================================
    # OLLAMA LLM INTEGRATION
    # ========================================

    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama for code generation using shared client."""
        from app.infrastructure.ollama_client import get_ollama_client

        client = get_ollama_client()
        model = self._settings.get("coding_model")  # explicit override or None
        timeout = self._settings.get("ollama_timeout", 300)
        retries = self._settings.get("max_ollama_retries", 2)

        return await client.chat(
            prompt,
            model=model,
            task_type="coding",
            temperature=0.2,
            num_predict=4096,
            timeout=timeout,
            max_retries=retries,
        )

    # ========================================
    # VALIDATION
    # ========================================

    def _validate_code(self, code: str, file_path: str):
        """Validate generated code syntax."""
        if file_path.endswith(".py"):
            try:
                ast.parse(code)
            except SyntaxError as e:
                raise Exception(f"Python syntax error: {e}")

    def _clean_code_response(self, response: str) -> str:
        """Clean LLM response: strip markdown fences and artifacts."""
        text = response.strip()

        # Strip markdown code fences
        lines = text.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        return "\n".join(lines)

    # ========================================
    # HELPERS
    # ========================================

    async def _get_project_tree(self, project_path: str, max_depth: int = 3) -> str:
        """Get a file tree listing for a project directory."""
        path = Path(project_path)
        if not path.exists():
            return ""

        lines = []
        ignore_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".next", "dist", "build", ".cache", ".pytest_cache",
        }
        ignore_exts = {".pyc", ".pyo", ".so", ".o", ".class"}

        def _walk(p: Path, depth: int, prefix: str = ""):
            if depth > max_depth:
                return
            try:
                entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            except PermissionError:
                return

            for entry in entries[:50]:  # Cap per directory
                if entry.name.startswith(".") and entry.name not in (".env.example",):
                    if entry.is_dir() and entry.name in ignore_dirs:
                        continue
                if entry.is_dir() and entry.name in ignore_dirs:
                    continue
                if entry.suffix in ignore_exts:
                    continue

                if entry.is_dir():
                    lines.append(f"{prefix}{entry.name}/")
                    _walk(entry, depth + 1, prefix + "  ")
                else:
                    lines.append(f"{prefix}{entry.name}")

        _walk(path, 0)
        return "\n".join(lines[:200])  # Cap total lines

    async def _notify(self, title: str, message: str):
        """Send notification via the notification service."""
        try:
            from app.services.notification_service import get_notification_service
            from app.models.assistant import NotificationChannel
            svc = get_notification_service()
            await svc.create_notification(
                title=title,
                message=message,
                channel=NotificationChannel.DISCORD,
                source="agent",
            )
        except Exception as e:
            logger.warning("notification_failed", error=str(e))

    async def _save_current_state(self):
        """Persist current execution state."""
        state = {
            "status": self._status.value,
            "paused": self._paused,
            "task": self._current_task,
            "steps": [s.to_dict() for s in self._steps],
            "updated_at": datetime.utcnow().isoformat(),
        }
        await self._storage.write("current_task.json", state)

    async def _move_to_history(self, task: Dict[str, Any]):
        """Move completed task to history."""
        data = await self._storage.read("history.json")
        history = data.get("tasks", [])
        history.append(task)

        # Keep last 100
        history = history[-100:]
        await self._storage.write("history.json", {"tasks": history})

    async def _remove_from_queue(self, task_id: str):
        """Remove a task from the queue."""
        data = await self._storage.read("queue.json")
        tasks = data.get("tasks", [])
        tasks = [t for t in tasks if t.get("task_id") != task_id]
        await self._storage.write("queue.json", {"tasks": tasks})

    @staticmethod
    def _extract_project_name(title: str) -> str:
        """Extract project name from task title like '[zero] Fix something'."""
        if title.startswith("[") and "]" in title:
            return title[1:title.index("]")]
        return "zero"

    def _calc_duration(self) -> int:
        """Calculate execution duration in seconds."""
        if not self._current_task:
            return 0
        started = self._current_task.get("started_at")
        if not started:
            return 0
        try:
            start_dt = datetime.fromisoformat(started)
            return int((datetime.utcnow() - start_dt).total_seconds())
        except Exception:
            return 0


@lru_cache()
def get_task_execution_service() -> TaskExecutionService:
    """Get singleton TaskExecutionService instance."""
    return TaskExecutionService()
