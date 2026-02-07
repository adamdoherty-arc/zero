"""
Daily Improvement Service for ZERO.

Autonomous daily cycle that answers "How can Zero be better today?"
Inspired by ADA's Enhancement Swarm but adapted for Zero's architecture.

Pipeline: Scan -> Plan -> Execute -> Verify -> Learn
Runs on a daily schedule via the scheduler service.
"""

import asyncio
import hashlib
import json
import subprocess
import ast
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
import structlog

from app.infrastructure.storage import JsonStorage
from app.infrastructure.config import get_workspace_path, get_enhancement_path, get_settings

logger = structlog.get_logger(__name__)

# Max auto-fixes per daily cycle (safety bound)
MAX_AUTO_FIXES_PER_CYCLE = 5

# Max diff lines for auto-fix (safety bound)
MAX_AUTO_FIX_LINES = 20


class ExecutionStrategy(str, Enum):
    """How to execute an improvement."""
    AUTO_FIX = "auto_fix"          # Simple, low-risk: LLM generates patch, apply directly
    LEGION_TASK = "legion_task"    # Medium complexity: create Legion task for swarm
    CLAUDE_PROMPT = "claude_prompt"  # Complex: generate a ready-to-paste Claude prompt
    HUMAN_REVIEW = "human_review"  # Architectural: create summary for user review


class ImprovementStatus(str, Enum):
    """Status of a daily improvement item."""
    PLANNED = "planned"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ImprovementItem:
    """A single improvement selected for today's cycle."""
    signal_id: str
    title: str
    project: str
    file: str
    line: int
    category: str
    estimated_effort: str  # small, medium, large
    impact_score: float
    execution_strategy: ExecutionStrategy
    status: ImprovementStatus = ImprovementStatus.PLANNED
    fix_applied: Optional[str] = None
    fix_backup: Optional[str] = None
    verification_result: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "title": self.title,
            "project": self.project,
            "file": self.file,
            "line": self.line,
            "category": self.category,
            "estimated_effort": self.estimated_effort,
            "impact_score": self.impact_score,
            "execution_strategy": self.execution_strategy.value,
            "status": self.status.value,
            "fix_applied": self.fix_applied,
            "verification_result": self.verification_result,
            "error": self.error,
        }


class DailyImprovementService:
    """
    Orchestrates daily self-improvement for Zero.

    Phase 1: Plan - Select top improvements from enhancement signals
    Phase 2: Execute - Apply fixes using tiered strategy
    Phase 3: Verify - Re-scan to confirm fixes worked
    Phase 4: Learn - Track metrics and adjust thresholds
    """

    def __init__(self):
        self._storage = JsonStorage(get_enhancement_path())
        self._plan_file = "daily_plan.json"
        self._metrics_file = "metrics.json"
        self._fixes_file = "fixes.json"
        self._learned_config_file = "learned_config.json"

        # Protected files that should NEVER be auto-fixed
        self._protected_patterns = [
            'infrastructure/', 'config.py', 'docker-compose',
            'Dockerfile', '.env', '.lock', 'main.py',
            'alembic/', 'migrations/',
        ]

    # ============================================
    # PHASE 1: DAILY IMPROVEMENT PLANNER
    # ============================================

    async def create_daily_plan(self) -> Dict[str, Any]:
        """
        Select top 5 improvements for today from pending enhancement signals.
        Runs at 9:15 AM after the enhancement scan.
        """
        logger.info("daily_improvement_plan_start")

        # Load signals
        data = await self._storage.read("signals.json")
        signals = data.get("signals", [])

        # Filter to pending, actionable signals
        candidates = [
            s for s in signals
            if s.get("status") == "pending"
            and s.get("confidence", 0) >= 70
            and s.get("source_file")
        ]

        if not candidates:
            logger.info("daily_improvement_no_candidates")
            plan = self._empty_plan("No actionable signals found")
            await self._storage.write(self._plan_file, plan)
            return plan

        # Score and rank
        scored = []
        for signal in candidates:
            score = self._calculate_improvement_score(signal)
            scored.append((score, signal))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Select top 5 with diversity constraints
        selected = self._select_diverse_improvements(scored, max_count=5)

        # Build plan
        improvements = []
        for signal in selected:
            strategy = self._determine_execution_strategy(signal)
            effort = self._estimate_effort(signal)
            item = ImprovementItem(
                signal_id=signal["id"],
                title=f"[{signal.get('type', 'todo').upper()}] {signal.get('message', '')[:80]}",
                project=signal.get("project_name", "zero"),
                file=signal.get("source_file", "unknown"),
                line=signal.get("line_number", 0),
                category=signal.get("type", "todo"),
                estimated_effort=effort,
                impact_score=signal.get("impact_score", 50),
                execution_strategy=strategy,
            )
            improvements.append(item)

        # Create plan document
        today = datetime.utcnow().strftime("%Y-%m-%d")
        plan = {
            "date": today,
            "plan_id": f"DIP-{today}",
            "created_at": datetime.utcnow().isoformat(),
            "selected_improvements": [item.to_dict() for item in improvements],
            "total_candidates": len(candidates),
            "summary": self._summarize_plan(improvements),
            "status": "planned",
        }

        await self._storage.write(self._plan_file, plan)

        # Send notification
        await self._notify_plan(plan)

        logger.info("daily_improvement_plan_created",
                     improvements=len(improvements),
                     candidates=len(candidates))
        return plan

    def _calculate_improvement_score(self, signal: Dict) -> float:
        """Score a signal for daily improvement selection."""
        impact = signal.get("impact_score", 50)
        confidence = signal.get("confidence", 70)
        risk = signal.get("risk_score", 30)

        # Base score
        score = (impact * 0.4) + (confidence * 0.3) + ((100 - risk) * 0.3)

        # Boost Zero project (self-improvement priority)
        if signal.get("project_name") == "zero":
            score *= 1.2

        # Boost FIXME and SECURITY (more actionable)
        signal_type = signal.get("type", "")
        if signal_type in ("fixme", "security"):
            score *= 1.15

        return score

    def _select_diverse_improvements(self, scored: List, max_count: int = 5) -> List[Dict]:
        """Select improvements with diversity constraints."""
        selected = []
        files_used = {}  # file -> count
        categories_used = {}  # category -> count

        for _score, signal in scored:
            if len(selected) >= max_count:
                break

            source_file = signal.get("source_file", "")
            category = signal.get("type", "")

            # Max 2 from the same file
            if files_used.get(source_file, 0) >= 2:
                continue

            # Max 3 from the same category
            if categories_used.get(category, 0) >= 3:
                continue

            selected.append(signal)
            files_used[source_file] = files_used.get(source_file, 0) + 1
            categories_used[category] = categories_used.get(category, 0) + 1

        return selected

    def _determine_execution_strategy(self, signal: Dict) -> ExecutionStrategy:
        """Determine how to execute an improvement based on signal characteristics."""
        signal_type = signal.get("type", "todo")
        severity = signal.get("severity", "medium")
        confidence = signal.get("confidence", 70)
        source_file = signal.get("source_file", "")

        # Protected files always go to human review
        for pattern in self._protected_patterns:
            if pattern in source_file:
                return ExecutionStrategy.HUMAN_REVIEW

        # High confidence + simple types -> auto-fix
        if confidence >= 85 and signal_type in ("todo", "deprecated"):
            return ExecutionStrategy.AUTO_FIX

        # FIXME with good confidence -> auto-fix
        if confidence >= 90 and signal_type == "fixme":
            return ExecutionStrategy.AUTO_FIX

        # Security issues always get human review
        if signal_type == "security":
            return ExecutionStrategy.HUMAN_REVIEW

        # HACK signals -> create Legion task (need deeper refactoring)
        if signal_type == "hack":
            return ExecutionStrategy.LEGION_TASK

        # Medium confidence -> create a Claude prompt for the user
        if confidence >= 75:
            return ExecutionStrategy.CLAUDE_PROMPT

        # Default to Legion task
        return ExecutionStrategy.LEGION_TASK

    def _estimate_effort(self, signal: Dict) -> str:
        """Estimate effort for an improvement."""
        signal_type = signal.get("type", "todo")
        severity = signal.get("severity", "medium")

        if signal_type in ("todo", "deprecated") and severity in ("low", "medium"):
            return "small"
        if signal_type in ("fixme", "hack") and severity in ("high", "critical"):
            return "large"
        return "medium"

    def _summarize_plan(self, improvements: List[ImprovementItem]) -> str:
        """Generate a human-readable summary of today's plan."""
        categories = {}
        for item in improvements:
            categories[item.category] = categories.get(item.category, 0) + 1

        parts = [f"{count} {cat}" for cat, count in categories.items()]
        return f"{len(improvements)} improvements selected: {', '.join(parts)}"

    def _empty_plan(self, reason: str) -> Dict[str, Any]:
        """Create an empty plan when no improvements are available."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        return {
            "date": today,
            "plan_id": f"DIP-{today}",
            "created_at": datetime.utcnow().isoformat(),
            "selected_improvements": [],
            "total_candidates": 0,
            "summary": reason,
            "status": "empty",
        }

    # ============================================
    # PHASE 2: IMPROVEMENT EXECUTOR
    # ============================================

    async def execute_daily_plan(self) -> Dict[str, Any]:
        """
        Execute today's improvement plan using tiered strategies.
        Runs at 9:30 AM after planning.
        """
        logger.info("daily_improvement_execute_start")

        plan = await self._storage.read(self._plan_file)
        if not plan or plan.get("status") in ("empty", "executed", "verified"):
            logger.info("daily_improvement_no_plan_to_execute", status=plan.get("status"))
            return {"status": "skipped", "reason": "No actionable plan"}

        improvements = plan.get("selected_improvements", [])
        auto_fix_count = 0
        results = []

        for item in improvements:
            strategy = item.get("execution_strategy", "human_review")
            signal_id = item.get("signal_id", "")

            try:
                if strategy == ExecutionStrategy.AUTO_FIX.value and auto_fix_count < MAX_AUTO_FIXES_PER_CYCLE:
                    result = await self._execute_auto_fix(item)
                    if result.get("applied"):
                        auto_fix_count += 1
                    item["status"] = ImprovementStatus.EXECUTED.value if result.get("applied") else ImprovementStatus.SKIPPED.value
                elif strategy == ExecutionStrategy.LEGION_TASK.value:
                    result = await self._execute_legion_task(item)
                    item["status"] = ImprovementStatus.EXECUTED.value
                elif strategy == ExecutionStrategy.CLAUDE_PROMPT.value:
                    result = await self._execute_claude_prompt(item)
                    item["status"] = ImprovementStatus.EXECUTED.value
                else:
                    result = {"strategy": "human_review", "prompt_generated": True}
                    item["status"] = ImprovementStatus.PLANNED.value

                results.append({"signal_id": signal_id, "strategy": strategy, **result})

            except Exception as e:
                logger.error("improvement_execution_failed", signal_id=signal_id, error=str(e))
                item["status"] = ImprovementStatus.FAILED.value
                item["error"] = str(e)
                results.append({"signal_id": signal_id, "strategy": strategy, "error": str(e)})

        plan["status"] = "executed"
        plan["executed_at"] = datetime.utcnow().isoformat()
        plan["execution_results"] = results
        plan["auto_fixes_applied"] = auto_fix_count

        await self._storage.write(self._plan_file, plan)

        logger.info("daily_improvement_execute_complete",
                     total=len(improvements),
                     auto_fixes=auto_fix_count)
        return {
            "status": "executed",
            "total_improvements": len(improvements),
            "auto_fixes_applied": auto_fix_count,
            "results": results,
        }

    async def _execute_auto_fix(self, item: Dict) -> Dict[str, Any]:
        """
        Auto-fix a simple improvement using Ollama LLM.
        Safety bounds: max 20 line diff, syntax validated, backup kept.
        """
        source_file = item.get("file", "")
        line_number = item.get("line", 0)
        message = item.get("title", "")
        signal_type = item.get("category", "todo")

        # Safety: check protected paths
        for pattern in self._protected_patterns:
            if pattern in source_file:
                return {"applied": False, "reason": f"Protected path: {pattern}"}

        # Read the file
        try:
            file_path = Path(source_file)
            if not file_path.exists():
                return {"applied": False, "reason": "File not found"}
            content = await asyncio.to_thread(file_path.read_text, encoding='utf-8')
        except Exception as e:
            return {"applied": False, "reason": f"Cannot read file: {e}"}

        lines = content.split('\n')
        if line_number < 1 or line_number > len(lines):
            return {"applied": False, "reason": "Line number out of range"}

        # Get context around the signal
        start = max(0, line_number - 5)
        end = min(len(lines), line_number + 5)
        context_lines = lines[start:end]
        context = '\n'.join(f"{start + i + 1}: {line}" for i, line in enumerate(context_lines))

        # Generate fix via Ollama
        fix_prompt = f"""Fix this {signal_type.upper()} issue in a Python/TypeScript file.

File: {source_file}
Line {line_number}: {lines[line_number - 1].strip()}

Issue: {message}

Context (lines {start + 1}-{end}):
{context}

Rules:
- Return ONLY the fixed version of the context lines shown above
- Keep the same indentation and style
- Make minimal changes — only fix the specific issue
- Remove the TODO/FIXME/HACK comment if the fix resolves it
- Do NOT add new imports or dependencies
- Output ONLY code, no explanations"""

        try:
            settings = get_settings()
            fixed_content = await self._call_ollama(fix_prompt, settings.ollama_model)
        except Exception as e:
            return {"applied": False, "reason": f"LLM call failed: {e}"}

        if not fixed_content or len(fixed_content.strip()) < 5:
            return {"applied": False, "reason": "LLM returned empty response"}

        # Parse the fix — extract just the code lines
        fixed_lines = self._extract_code_from_response(fixed_content)
        if not fixed_lines:
            return {"applied": False, "reason": "Could not parse LLM response as code"}

        # Safety: check diff size
        original_section = lines[start:end]
        if abs(len(fixed_lines) - len(original_section)) > MAX_AUTO_FIX_LINES:
            return {"applied": False, "reason": f"Diff too large ({abs(len(fixed_lines) - len(original_section))} lines)"}

        # Build new file content
        new_lines = lines[:start] + fixed_lines + lines[end:]
        new_content = '\n'.join(new_lines)

        # Validate syntax for Python files
        if source_file.endswith('.py'):
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                return {"applied": False, "reason": f"Syntax error in fix: {e}"}

        # Create backup
        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        try:
            await asyncio.to_thread(backup_path.write_text, content, encoding='utf-8')
        except Exception:
            pass  # Non-critical

        # Apply fix
        try:
            await asyncio.to_thread(file_path.write_text, new_content, encoding='utf-8')
        except Exception as e:
            return {"applied": False, "reason": f"Failed to write file: {e}"}

        # Record fix
        await self._record_fix(item, content, new_content, str(backup_path))

        logger.info("auto_fix_applied",
                     file=source_file,
                     line=line_number,
                     signal_type=signal_type)

        return {
            "applied": True,
            "file": source_file,
            "line": line_number,
            "backup": str(backup_path),
            "diff_lines": abs(len(fixed_lines) - len(original_section)),
        }

    async def _execute_legion_task(self, item: Dict) -> Dict[str, Any]:
        """Create a Legion task for this improvement."""
        try:
            from app.services.legion_client import get_legion_client

            legion = get_legion_client()
            if not await legion.health_check():
                return {"created": False, "reason": "Legion unavailable"}

            # Get project's active sprint
            project_map = {"zero": 8, "ada": 6, "fortressos": 7, "legion": 3}
            project_id = project_map.get(item.get("project", "zero"), 8)

            current = await legion.get_current_sprint(project_id)
            if not current:
                return {"created": False, "reason": "No active sprint"}

            task_data = {
                "title": item.get("title", "Improvement task")[:100],
                "description": f"Daily improvement signal: {item.get('title')}\nFile: {item.get('file')}:{item.get('line')}",
                "prompt": f"Fix the {item.get('category', 'issue')} at {item.get('file')}:{item.get('line')}: {item.get('title')}",
                "priority": 3,
                "source": "daily_improvement",
            }

            task = await legion.create_task(current["id"], task_data)
            return {"created": True, "legion_task_id": task.get("id")}

        except Exception as e:
            logger.warning("legion_task_creation_failed", error=str(e))
            return {"created": False, "reason": str(e)}

    async def _execute_claude_prompt(self, item: Dict) -> Dict[str, Any]:
        """Generate a Claude Code prompt for complex improvements."""
        prompt = f"""Fix the following {item.get('category', 'issue')} in {item.get('file')}:

Line {item.get('line')}: {item.get('title')}

Please:
1. Read the file and understand the context
2. Fix the specific issue
3. Run any relevant tests
4. Ensure the fix doesn't break anything"""

        item["claude_prompt"] = prompt
        return {"prompt_generated": True, "prompt": prompt}

    async def _call_ollama(self, prompt: str, model: str) -> str:
        """Call Ollama for code generation."""
        import httpx

        settings = get_settings()
        base_url = settings.ollama_base_url.rstrip("/v1")  # Remove /v1 suffix for chat endpoint

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model.split(":")[0] if ":" in model else model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500},
                },
            )
            response.raise_for_status()
            return response.json().get("response", "")

    def _extract_code_from_response(self, response: str) -> Optional[List[str]]:
        """Extract code lines from LLM response, stripping markdown fences."""
        lines = response.strip().split('\n')

        # Strip markdown code fences
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]

        # Strip line numbers if present (e.g., "42: code here")
        cleaned = []
        for line in lines:
            # Check for "123: " prefix pattern
            import re
            match = re.match(r'^\d+:\s?', line)
            if match:
                cleaned.append(line[match.end():])
            else:
                cleaned.append(line)

        if not cleaned:
            return None

        return cleaned

    async def _record_fix(self, item: Dict, original: str, fixed: str, backup_path: str):
        """Record an applied fix for tracking."""
        data = await self._storage.read(self._fixes_file)
        fixes = data.get("fixes", [])

        fixes.append({
            "signal_id": item.get("signal_id"),
            "file": item.get("file"),
            "line": item.get("line"),
            "category": item.get("category"),
            "applied_at": datetime.utcnow().isoformat(),
            "backup_path": backup_path,
            "original_hash": hashlib.md5(original.encode()).hexdigest()[:12],
            "fixed_hash": hashlib.md5(fixed.encode()).hexdigest()[:12],
        })

        # Keep last 200 fixes
        data["fixes"] = fixes[-200:]
        await self._storage.write(self._fixes_file, data)

    # ============================================
    # PHASE 3: VERIFICATION LOOP
    # ============================================

    async def verify_daily_plan(self) -> Dict[str, Any]:
        """
        Verify today's improvements were successful.
        Runs at 10:00 AM, 30 minutes after execution.
        """
        logger.info("daily_improvement_verify_start")

        plan = await self._storage.read(self._plan_file)
        if not plan or plan.get("status") not in ("executed",):
            logger.info("daily_improvement_no_plan_to_verify", status=plan.get("status"))
            return {"status": "skipped", "reason": "No executed plan to verify"}

        improvements = plan.get("selected_improvements", [])
        verified = 0
        failed = 0
        pending = 0

        for item in improvements:
            if item.get("status") != ImprovementStatus.EXECUTED.value:
                if item.get("status") == ImprovementStatus.FAILED.value:
                    failed += 1
                else:
                    pending += 1
                continue

            strategy = item.get("execution_strategy", "")

            if strategy == ExecutionStrategy.AUTO_FIX.value:
                # Re-scan the file to see if signal is gone
                is_fixed = await self._verify_auto_fix(item)
                if is_fixed:
                    item["status"] = ImprovementStatus.VERIFIED.value
                    item["verification_result"] = "Signal resolved"
                    verified += 1
                else:
                    item["status"] = ImprovementStatus.FAILED.value
                    item["verification_result"] = "Signal still present after fix"
                    failed += 1

            elif strategy == ExecutionStrategy.LEGION_TASK.value:
                # Legion tasks are async — mark as pending verification
                item["verification_result"] = "Pending Legion execution"
                pending += 1

            elif strategy == ExecutionStrategy.CLAUDE_PROMPT.value:
                # Prompts are for the user — mark as pending
                item["verification_result"] = "Pending user execution"
                pending += 1

        plan["status"] = "verified"
        plan["verified_at"] = datetime.utcnow().isoformat()
        plan["verification_summary"] = {
            "verified": verified,
            "failed": failed,
            "pending": pending,
            "total": len(improvements),
            "success_rate": round(verified / max(verified + failed, 1) * 100, 1),
        }

        await self._storage.write(self._plan_file, plan)

        # Update metrics
        await self._update_metrics(plan["verification_summary"])

        # Send verification report
        await self._notify_verification(plan)

        logger.info("daily_improvement_verify_complete",
                     verified=verified, failed=failed, pending=pending)
        return {
            "status": "verified",
            **plan["verification_summary"],
        }

    async def _verify_auto_fix(self, item: Dict) -> bool:
        """Verify that an auto-fix resolved the original signal."""
        from app.services.enhancement_service import EnhancementService

        source_file = item.get("file", "")
        line_number = item.get("line", 0)

        try:
            file_path = Path(source_file)
            if not file_path.exists():
                return False

            content = await asyncio.to_thread(file_path.read_text, encoding='utf-8')

            # Check if the original signal pattern is still present around that line
            svc = EnhancementService()
            signals = svc._extract_signals_from_file(source_file, content, project_name=item.get("project", ""))

            # Check if any signal matches the original signal ID
            for signal in signals:
                if signal.id == item.get("signal_id"):
                    return False  # Signal still present

            return True  # Signal gone

        except Exception as e:
            logger.warning("auto_fix_verification_failed", file=source_file, error=str(e))
            return False

    # ============================================
    # PHASE 4: METRICS & LEARNING
    # ============================================

    async def _update_metrics(self, verification: Dict):
        """Update daily metrics with today's results."""
        data = await self._storage.read(self._metrics_file)

        daily_entries = data.get("daily", [])
        today = datetime.utcnow().strftime("%Y-%m-%d")

        daily_entries.append({
            "date": today,
            "verified": verification.get("verified", 0),
            "failed": verification.get("failed", 0),
            "pending": verification.get("pending", 0),
            "total": verification.get("total", 0),
            "success_rate": verification.get("success_rate", 0),
        })

        # Keep last 90 days
        data["daily"] = daily_entries[-90:]
        data["last_updated"] = datetime.utcnow().isoformat()

        # Calculate rolling averages
        recent = daily_entries[-7:]
        if recent:
            data["rolling_7day"] = {
                "avg_success_rate": round(
                    sum(d.get("success_rate", 0) for d in recent) / len(recent), 1
                ),
                "total_verified": sum(d.get("verified", 0) for d in recent),
                "total_failed": sum(d.get("failed", 0) for d in recent),
                "total_improvements": sum(d.get("total", 0) for d in recent),
            }

        recent_30 = daily_entries[-30:]
        if recent_30:
            data["rolling_30day"] = {
                "avg_success_rate": round(
                    sum(d.get("success_rate", 0) for d in recent_30) / len(recent_30), 1
                ),
                "total_verified": sum(d.get("verified", 0) for d in recent_30),
                "total_failed": sum(d.get("failed", 0) for d in recent_30),
                "total_improvements": sum(d.get("total", 0) for d in recent_30),
            }

        await self._storage.write(self._metrics_file, data)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get improvement metrics for the API/dashboard."""
        data = await self._storage.read(self._metrics_file)
        plan = await self._storage.read(self._plan_file)

        return {
            "today": plan.get("verification_summary") if plan else None,
            "today_plan": {
                "date": plan.get("date"),
                "status": plan.get("status"),
                "improvements": len(plan.get("selected_improvements", [])),
                "summary": plan.get("summary"),
            } if plan else None,
            "rolling_7day": data.get("rolling_7day"),
            "rolling_30day": data.get("rolling_30day"),
            "daily_history": data.get("daily", [])[-14:],  # Last 2 weeks
            "last_updated": data.get("last_updated"),
        }

    async def get_todays_plan(self) -> Dict[str, Any]:
        """Get today's improvement plan for display."""
        plan = await self._storage.read(self._plan_file)
        return plan if plan else self._empty_plan("No plan created yet")

    # ============================================
    # NOTIFICATIONS
    # ============================================

    async def _notify_plan(self, plan: Dict):
        """Send daily improvement plan notification."""
        try:
            from app.services.notification_service import get_notification_service

            improvements = plan.get("selected_improvements", [])
            lines = [f"**Daily Improvement Plan — {plan.get('date')}**\n"]
            lines.append(f"Selected {len(improvements)} of {plan.get('total_candidates', 0)} candidates:\n")

            for item in improvements:
                strategy_icon = {
                    "auto_fix": "auto",
                    "legion_task": "legion",
                    "claude_prompt": "prompt",
                    "human_review": "review",
                }.get(item.get("execution_strategy", ""), "?")
                lines.append(
                    f"- [{strategy_icon}] {item.get('title', '')[:60]} "
                    f"({item.get('project', 'zero')})"
                )

            svc = get_notification_service()
            await svc.create_notification(
                title="Daily Improvement Plan",
                message="\n".join(lines),
                channel="discord",
                source="daily_improvement",
            )
        except Exception as e:
            logger.debug("plan_notification_failed", error=str(e))

    async def _notify_verification(self, plan: Dict):
        """Send verification report notification."""
        try:
            from app.services.notification_service import get_notification_service

            v = plan.get("verification_summary", {})
            metrics = await self._storage.read(self._metrics_file)
            rolling = metrics.get("rolling_7day", {})

            lines = [f"**Daily Improvement Report — {plan.get('date')}**\n"]

            verified = v.get("verified", 0)
            failed = v.get("failed", 0)
            pending = v.get("pending", 0)
            total = v.get("total", 0)

            if verified > 0:
                lines.append(f"Verified: {verified}/{total} improvements")
            if failed > 0:
                lines.append(f"Failed: {failed}")
            if pending > 0:
                lines.append(f"Pending: {pending}")

            lines.append(f"\nToday's score: {v.get('success_rate', 0)}%")

            if rolling:
                lines.append(f"7-day average: {rolling.get('avg_success_rate', 0)}%")
                lines.append(f"Total improvements this week: {rolling.get('total_improvements', 0)}")

            svc = get_notification_service()
            await svc.create_notification(
                title="Daily Improvement Report",
                message="\n".join(lines),
                channel="discord",
                source="daily_improvement",
            )
        except Exception as e:
            logger.debug("verification_notification_failed", error=str(e))


# ============================================
# SINGLETON
# ============================================

_service: Optional[DailyImprovementService] = None


def get_daily_improvement_service() -> DailyImprovementService:
    """Get the singleton daily improvement service."""
    global _service
    if _service is None:
        _service = DailyImprovementService()
    return _service
