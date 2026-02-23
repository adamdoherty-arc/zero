"""
Enhancement Service.
Detects signals from multiple sources and creates sprint tasks.
Based on ADA's autonomous enhancement agent patterns.

Persistence: PostgreSQL via SQLAlchemy async (EnhancementSignalModel, ServiceConfigModel).
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
import structlog

from sqlalchemy import select, update, func as sa_func

from app.infrastructure.database import get_session
from app.infrastructure.config import get_workspace_path, get_settings
from app.db.models import EnhancementSignalModel, ServiceConfigModel
from app.models.task import TaskCreate, TaskCategory, TaskPriority, TaskSource

logger = structlog.get_logger()

# Multi-project scan configuration: project name -> scan dirs + Legion project ID
SCAN_PROJECTS = {
    "zero": {"dirs": ["backend", "frontend", "skills"], "legion_id": 8},
    "ada": {"dirs": ["src", "backend", "frontend"], "legion_id": 6},
    "fortressos": {"dirs": ["src", "backend", "frontend"], "legion_id": 7},
    "legion": {"dirs": ["backend", "src"], "legion_id": 3},
}


class SignalType(str, Enum):
    """Types of enhancement signals."""
    TODO = "todo"
    FIXME = "fixme"
    HACK = "hack"
    ERROR_PATTERN = "error_pattern"
    PERFORMANCE = "performance"
    SECURITY = "security"
    DEPRECATED = "deprecated"


class SignalSeverity(str, Enum):
    """Severity levels for signals."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EnhancementSignal:
    """Represents a detected enhancement signal."""
    id: str
    type: SignalType
    message: str
    severity: SignalSeverity
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    context: Optional[str] = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "pending"  # pending, converted, dismissed
    confidence: float = 80.0
    impact_score: float = 50.0
    risk_score: float = 30.0
    project_name: str = ""  # Which project this signal belongs to

    @property
    def priority_score(self) -> float:
        """Calculate priority: (impact * 0.4) + ((100 - risk) * 0.3) + (confidence * 0.3)"""
        return (self.impact_score * 0.4) + ((100 - self.risk_score) * 0.3) + (self.confidence * 0.3)


class EnhancementService:
    """
    Service for detecting enhancement signals and creating tasks.
    """

    def __init__(self):
        # Patterns for code scanning
        self.todo_patterns = [
            (r'#\s*TODO[:\s]*(.*)', SignalType.TODO, SignalSeverity.MEDIUM),
            (r'//\s*TODO[:\s]*(.*)', SignalType.TODO, SignalSeverity.MEDIUM),
            (r'#\s*FIXME[:\s]*(.*)', SignalType.FIXME, SignalSeverity.HIGH),
            (r'//\s*FIXME[:\s]*(.*)', SignalType.FIXME, SignalSeverity.HIGH),
            (r'#\s*HACK[:\s]*(.*)', SignalType.HACK, SignalSeverity.MEDIUM),
            (r'//\s*HACK[:\s]*(.*)', SignalType.HACK, SignalSeverity.MEDIUM),
            (r'#\s*XXX[:\s]*(.*)', SignalType.HACK, SignalSeverity.HIGH),
            (r'//\s*XXX[:\s]*(.*)', SignalType.HACK, SignalSeverity.HIGH),
            (r'#\s*SECURITY[:\s]*(.*)', SignalType.SECURITY, SignalSeverity.CRITICAL),
            (r'#\s*DEPRECATED[:\s]*(.*)', SignalType.DEPRECATED, SignalSeverity.LOW),
        ]

        # File extensions to scan (code only — .md excluded to reduce false positives)
        self.scan_extensions = {'.py', '.ts', '.tsx', '.js', '.jsx', '.yaml', '.yml'}

        # Files/patterns to never create tasks from (infrastructure, config, generated)
        self.protected_paths = {'infrastructure/', 'config.py', 'docker-compose', 'Dockerfile', '.lock'}

        # Track previously seen signals to only surface NEW ones
        self._previous_signal_ids: set = set()

    async def scan_for_signals(self) -> Dict[str, Any]:
        """
        Scan codebase for enhancement signals from multiple sources.
        """
        logger.info("Starting enhancement signal scan")

        signals: List[EnhancementSignal] = []

        # Source 1: TODO/FIXME comments in code
        code_signals = await self._scan_code_comments()
        signals.extend(code_signals)

        # Source 2: Error patterns from logs (if available)
        # error_signals = await self._scan_error_logs()
        # signals.extend(error_signals)

        # Deduplicate and prioritize
        unique_signals = self._deduplicate_signals(signals)
        prioritized = sorted(unique_signals, key=lambda s: s.priority_score, reverse=True)

        # Persist signals
        await self._persist_signals(prioritized)

        logger.info("Enhancement scan complete",
                   total_signals=len(prioritized),
                   by_type={t.value: len([s for s in prioritized if s.type == t]) for t in SignalType})

        return {
            "status": "completed",
            "signals_found": len(prioritized),
            "by_type": {t.value: len([s for s in prioritized if s.type == t]) for t in SignalType},
            "by_severity": {s.value: len([sig for sig in prioritized if sig.severity == s]) for s in SignalSeverity}
        }

    async def scan_all_projects(self) -> Dict[str, Any]:
        """
        Scan all mounted project codebases for enhancement signals.
        Returns per-project signal counts for orchestration.
        Tracks new vs. previously-seen signals for deduplication across runs.
        """
        settings = get_settings()
        projects_root = Path(settings.projects_root)

        # Load previously seen signal IDs from the database
        async with get_session() as session:
            result = await session.execute(
                select(EnhancementSignalModel.id)
            )
            previously_seen = {row for row in result.scalars().all()}

        all_signals: List[EnhancementSignal] = []
        per_project: Dict[str, Dict[str, Any]] = {}

        for project_name, config in SCAN_PROJECTS.items():
            project_dir = projects_root / project_name
            if not project_dir.exists():
                logger.warning("project_dir_not_found", project=project_name, path=str(project_dir))
                per_project[project_name] = {"signals": 0, "skipped": True}
                continue

            scan_dirs = [project_dir / d for d in config["dirs"]]
            project_signals = await self._scan_directories(scan_dirs, project_name)
            all_signals.extend(project_signals)
            per_project[project_name] = {
                "signals": len(project_signals),
                "legion_id": config["legion_id"],
                "skipped": False,
            }
            logger.info("project_scan_complete", project=project_name, signals=len(project_signals))

        # Deduplicate and prioritize
        unique_signals = self._deduplicate_signals(all_signals)
        prioritized = sorted(unique_signals, key=lambda s: s.priority_score, reverse=True)

        # Count new signals (not seen in previous scans)
        new_signal_ids = {s.id for s in prioritized} - previously_seen
        new_count = len(new_signal_ids)

        # Persist
        await self._persist_signals(prioritized)

        logger.info("multi_project_scan_complete",
                     total_signals=len(prioritized),
                     new_signals=new_count,
                     projects_scanned=len([p for p in per_project.values() if not p.get("skipped")]))

        return {
            "status": "completed",
            "signals_found": len(prioritized),
            "new_signals": new_count,
            "per_project": per_project,
            "by_type": {t.value: len([s for s in prioritized if s.type == t]) for t in SignalType},
            "by_severity": {s.value: len([sig for sig in prioritized if sig.severity == s]) for s in SignalSeverity},
        }

    async def _scan_directories(
        self, scan_dirs: List[Path], project_name: str = ""
    ) -> List[EnhancementSignal]:
        """Scan directories for enhancement signals (runs in thread to avoid blocking event loop)."""
        return await asyncio.to_thread(self._scan_directories_sync, scan_dirs, project_name)

    def _scan_directories_sync(
        self, scan_dirs: List[Path], project_name: str = ""
    ) -> List[EnhancementSignal]:
        """Synchronous directory scan (runs in a thread pool)."""
        signals = []
        skip_dirs = {"node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv", ".tox"}
        max_file_size = 512 * 1024  # Skip files > 512KB

        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue

            for file_path in scan_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix not in self.scan_extensions:
                    continue
                if any(part in skip_dirs for part in file_path.parts):
                    continue

                try:
                    if file_path.stat().st_size > max_file_size:
                        continue
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    file_signals = self._extract_signals_from_file(
                        str(file_path), content, project_name=project_name
                    )
                    signals.extend(file_signals)
                except Exception as e:
                    logger.warning("Error scanning file", file=str(file_path), error=str(e))

        return signals

    async def _scan_code_comments(self) -> List[EnhancementSignal]:
        """Scan Zero's code files for TODO/FIXME/HACK comments."""
        # Get workspace root (parent of workspace dir)
        workspace = get_workspace_path()
        project_root = workspace.parent

        scan_dirs = [
            project_root / "backend",
            project_root / "frontend",
            project_root / "skills",
        ]

        return await self._scan_directories(scan_dirs, project_name="zero")

    def _extract_signals_from_file(
        self, file_path: str, content: str, project_name: str = ""
    ) -> List[EnhancementSignal]:
        """Extract signals from a single file with context-aware filtering."""
        signals = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            for pattern, signal_type, severity in self.todo_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    message = match.group(1).strip() if match.groups() else line.strip()

                    # Context-aware filtering: skip non-actionable signals
                    if self._is_false_positive(file_path, line, message, signal_type):
                        continue

                    # Generate unique ID based on file + line + message
                    signal_hash = hashlib.md5(f"{file_path}:{line_num}:{message[:50]}".encode()).hexdigest()[:12]

                    # Calculate scores based on signal type
                    impact, confidence = self._calculate_signal_scores(signal_type, severity, message)

                    # Apply minimum threshold: skip low-value signals
                    if severity == SignalSeverity.LOW and confidence < 75:
                        continue

                    signal = EnhancementSignal(
                        id=f"SIG_{signal_hash}",
                        type=signal_type,
                        message=message[:500],
                        severity=severity,
                        source_file=file_path,
                        line_number=line_num,
                        context=self._get_context(lines, line_num),
                        confidence=confidence,
                        impact_score=impact,
                        risk_score=self._calculate_risk(signal_type),
                        project_name=project_name,
                    )
                    signals.append(signal)

        return signals

    def _is_false_positive(self, file_path: str, line: str, message: str, signal_type: SignalType) -> bool:
        """Filter out non-actionable signals that are documentation or comments about concepts."""
        # Skip signals in protected infrastructure paths
        for protected in self.protected_paths:
            if protected in file_path:
                return True

        # Skip markdown documentation headers that match patterns
        # e.g., "## Security Considerations", "### TODO List Template"
        if file_path.endswith('.md'):
            return True

        # Skip signals inside docstrings/comments that describe concepts rather than actionable items
        stripped = line.strip()

        # Skip if the "TODO" etc. is inside a string literal (common in templates/examples)
        if signal_type == SignalType.TODO:
            # "TODO" in example code or documentation strings
            if '"""' in line or "'''" in line or 'example' in line.lower():
                return True

        # Skip signals with empty or trivially short messages (likely false positives)
        if len(message) < 5:
            return True

        # Skip test files that contain pattern comments for testing purposes
        if '/tests/' in file_path or '\\tests\\' in file_path or '_test.' in file_path:
            if signal_type in (SignalType.TODO, SignalType.DEPRECATED):
                return True

        # Skip SECURITY signals that are just section headers (e.g., "# SECURITY: Notes on...")
        if signal_type == SignalType.SECURITY:
            non_actionable = ['considerations', 'notes', 'overview', 'guide', 'policy', 'requirements']
            if any(word in message.lower() for word in non_actionable):
                return True

        return False

    def _calculate_signal_scores(self, signal_type: SignalType, severity: SignalSeverity, message: str) -> tuple:
        """Calculate impact and confidence scores."""
        # Base impact by severity
        severity_impact = {
            SignalSeverity.CRITICAL: 90,
            SignalSeverity.HIGH: 70,
            SignalSeverity.MEDIUM: 50,
            SignalSeverity.LOW: 30
        }

        # Base confidence by signal type
        type_confidence = {
            SignalType.FIXME: 90,
            SignalType.SECURITY: 95,
            SignalType.TODO: 80,
            SignalType.HACK: 85,
            SignalType.DEPRECATED: 75,
            SignalType.ERROR_PATTERN: 70,
            SignalType.PERFORMANCE: 65
        }

        impact = severity_impact.get(severity, 50)
        confidence = type_confidence.get(signal_type, 70)

        # Boost impact if message contains urgent keywords
        urgent_keywords = ['urgent', 'critical', 'asap', 'important', 'bug', 'broken', 'security']
        if any(kw in message.lower() for kw in urgent_keywords):
            impact = min(100, impact + 15)
            confidence = min(100, confidence + 10)

        return impact, confidence

    def _calculate_risk(self, signal_type: SignalType) -> float:
        """Calculate risk score for a signal type."""
        risk_scores = {
            SignalType.SECURITY: 80,
            SignalType.HACK: 60,
            SignalType.FIXME: 40,
            SignalType.TODO: 20,
            SignalType.DEPRECATED: 30,
            SignalType.ERROR_PATTERN: 50,
            SignalType.PERFORMANCE: 25
        }
        return risk_scores.get(signal_type, 30)

    def _get_context(self, lines: List[str], line_num: int, context_lines: int = 2) -> str:
        """Get surrounding context for a signal."""
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        return '\n'.join(lines[start:end])

    def _deduplicate_signals(self, signals: List[EnhancementSignal]) -> List[EnhancementSignal]:
        """Remove duplicate signals based on ID."""
        seen = set()
        unique = []
        for signal in signals:
            if signal.id not in seen:
                seen.add(signal.id)
                unique.append(signal)
        return unique

    async def _persist_signals(self, signals: List[EnhancementSignal]) -> None:
        """Persist signals to PostgreSQL, preserving status of existing signals."""
        new_count = 0

        async with get_session() as session:
            # Fetch existing signal IDs and their statuses in one query
            existing_ids = {s.id for s in signals}
            if existing_ids:
                result = await session.execute(
                    select(
                        EnhancementSignalModel.id,
                        EnhancementSignalModel.status,
                    ).where(EnhancementSignalModel.id.in_(existing_ids))
                )
                existing_map: Dict[str, str] = {row.id: row.status for row in result.all()}
            else:
                existing_map = {}

            for s in signals:
                existing_status = existing_map.get(s.id)

                if existing_status is not None:
                    # Signal exists -- update fields but preserve status if converted/dismissed
                    preserved_status = (
                        existing_status
                        if existing_status in ("converted", "dismissed")
                        else s.status
                    )
                    await session.execute(
                        update(EnhancementSignalModel)
                        .where(EnhancementSignalModel.id == s.id)
                        .values(
                            type=s.type.value,
                            message=s.message,
                            severity=s.severity.value,
                            source_file=s.source_file,
                            line_number=s.line_number,
                            context=s.context,
                            status=preserved_status,
                            confidence=s.confidence,
                            impact_score=s.impact_score,
                            risk_score=s.risk_score,
                            priority_score=s.priority_score,
                            project_name=s.project_name,
                        )
                    )
                else:
                    # New signal -- insert
                    session.add(EnhancementSignalModel(
                        id=s.id,
                        type=s.type.value,
                        message=s.message,
                        severity=s.severity.value,
                        source_file=s.source_file,
                        line_number=s.line_number,
                        context=s.context,
                        status=s.status,
                        confidence=s.confidence,
                        impact_score=s.impact_score,
                        risk_score=s.risk_score,
                        priority_score=s.priority_score,
                        project_name=s.project_name,
                        detected_at=s.detected_at,
                    ))
                    new_count += 1

            # Update scan metadata in ServiceConfigModel
            now_iso = datetime.now(timezone.utc).isoformat()

            # Fetch current config to increment scanCount
            cfg_result = await session.execute(
                select(ServiceConfigModel).where(
                    ServiceConfigModel.service_name == "enhancement"
                )
            )
            cfg_row = cfg_result.scalar_one_or_none()

            if cfg_row is not None:
                current_config = cfg_row.config or {}
                current_config["lastScanAt"] = now_iso
                current_config["scanCount"] = current_config.get("scanCount", 0) + 1
                await session.execute(
                    update(ServiceConfigModel)
                    .where(ServiceConfigModel.service_name == "enhancement")
                    .values(config=current_config)
                )
            else:
                session.add(ServiceConfigModel(
                    service_name="enhancement",
                    config={"lastScanAt": now_iso, "scanCount": 1},
                ))

        logger.info("Signals persisted", count=len(signals), new=new_count)

    async def create_tasks_from_signals(self, sprint_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create sprint tasks from pending signals.
        Auto-converts high-confidence signals, queues others for review.
        """
        from app.services.task_service import get_task_service
        task_service = get_task_service()

        # Read pending signals from the database
        async with get_session() as session:
            result = await session.execute(
                select(EnhancementSignalModel).where(
                    EnhancementSignalModel.status == "pending"
                )
            )
            pending_rows = result.scalars().all()

            created_tasks = []
            skipped = []

            for row in pending_rows:
                # Check if should auto-create based on confidence
                confidence = row.confidence
                severity = row.severity

                # Auto-create thresholds based on severity
                auto_threshold = {
                    "critical": 70,
                    "high": 80,
                    "medium": 85,
                    "low": 90
                }.get(severity, 85)

                if confidence >= auto_threshold:
                    # Build a signal dict for _signal_to_task
                    signal_data = self._row_to_dict(row)
                    task_data = self._signal_to_task(signal_data, sprint_id)
                    task = await task_service.create_task(task_data)

                    # Update signal status in DB
                    row.status = "converted"
                    row.converted_to_task = task.id
                    row.converted_at = datetime.now(timezone.utc)

                    created_tasks.append({
                        "signal_id": row.id,
                        "task_id": task.id,
                        "title": task.title
                    })

                    logger.info("Task created from signal",
                              signal_id=row.id,
                              task_id=task.id)
                else:
                    skipped.append({
                        "signal_id": row.id,
                        "reason": f"Confidence {confidence}% below threshold {auto_threshold}%"
                    })

            # Session auto-commits on context manager exit

        return {
            "status": "completed",
            "tasks_created": len(created_tasks),
            "tasks_skipped": len(skipped),
            "created": created_tasks,
            "skipped": skipped
        }

    def _signal_to_task(self, signal: Dict, sprint_id: Optional[str]) -> TaskCreate:
        """Convert a signal to a task creation request."""
        signal_type = signal.get("type", "todo")
        severity = signal.get("severity", "medium")

        # Map signal type to category
        category_map = {
            "todo": TaskCategory.CHORE,
            "fixme": TaskCategory.BUG,
            "hack": TaskCategory.ENHANCEMENT,
            "security": TaskCategory.BUG,
            "deprecated": TaskCategory.CHORE,
            "error_pattern": TaskCategory.BUG,
            "performance": TaskCategory.ENHANCEMENT
        }

        # Map severity to priority
        priority_map = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW
        }

        # Generate title
        message = signal.get("message", "Enhancement task")[:80]
        title = f"[{signal_type.upper()}] {message}"

        # Generate description
        source_file = signal.get("source_file", "unknown")
        line_number = signal.get("line_number", "?")
        description = f"""**Source:** `{source_file}:{line_number}`

**Signal:** {signal.get("message", "")}

**Context:**
```
{signal.get("context", "No context available")}
```

**Detected:** {signal.get("detected_at", "")}
**Confidence:** {signal.get("confidence", 0)}%
"""

        # Estimate points based on signal type and severity
        points_map = {
            ("critical", "fixme"): 8,
            ("critical", "security"): 13,
            ("high", "fixme"): 5,
            ("high", "todo"): 5,
            ("medium", "todo"): 3,
            ("medium", "hack"): 5,
            ("low", "todo"): 2,
            ("low", "deprecated"): 2
        }
        points = points_map.get((severity, signal_type), 3)

        return TaskCreate(
            title=title,
            description=description,
            sprint_id=sprint_id,
            category=category_map.get(signal_type, TaskCategory.CHORE),
            priority=priority_map.get(severity, TaskPriority.MEDIUM),
            points=points,
            source=TaskSource.ENHANCEMENT_ENGINE,
            source_reference=signal.get("id")
        )

    async def create_legion_tasks_from_signals(
        self,
        project_id: int,
        sprint_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create tasks in Legion from pending signals.

        This is the preferred method - tasks go directly to Legion
        as THE central sprint manager.
        """
        from app.services.legion_client import get_legion_client, LegionConnectionError

        legion = get_legion_client()

        # Check if Legion is reachable
        try:
            if not await legion.health_check():
                return {
                    "status": "error",
                    "error": "Legion is not reachable",
                    "tasks_created": 0
                }
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to connect to Legion: {str(e)}",
                "tasks_created": 0
            }

        # Get current sprint if not provided
        if not sprint_id:
            current = await legion.get_current_sprint(project_id)
            if not current:
                return {
                    "status": "error",
                    "error": f"No active sprint found for project {project_id}",
                    "tasks_created": 0
                }
            sprint_id = current["id"]

        # Get pending signals from the database
        async with get_session() as session:
            result = await session.execute(
                select(EnhancementSignalModel).where(
                    EnhancementSignalModel.status == "pending"
                )
            )
            pending_rows = result.scalars().all()

            created_tasks = []
            skipped = []
            errors = []

            for row in pending_rows:
                # Check if should auto-create based on confidence
                confidence = row.confidence
                severity = row.severity

                # Auto-create thresholds
                auto_threshold = {
                    "critical": 70,
                    "high": 80,
                    "medium": 85,
                    "low": 90
                }.get(severity, 85)

                if confidence >= auto_threshold:
                    # Map signal to Legion task format
                    signal_data = self._row_to_dict(row)
                    task_data = self._signal_to_legion_task(signal_data)

                    try:
                        # Create task in Legion
                        task = await legion.create_task(sprint_id, task_data)

                        # Update signal status in DB
                        row.status = "converted"
                        row.converted_to_legion_task = task.get("id")
                        row.converted_at = datetime.now(timezone.utc)

                        created_tasks.append({
                            "signal_id": row.id,
                            "legion_task_id": task.get("id"),
                            "title": task_data["title"]
                        })

                        logger.info(
                            "Legion task created from signal",
                            signal_id=row.id,
                            task_id=task.get("id")
                        )
                    except Exception as e:
                        errors.append({
                            "signal_id": row.id,
                            "error": str(e)
                        })
                        logger.warning(
                            "Failed to create Legion task",
                            signal_id=row.id,
                            error=str(e)
                        )
                else:
                    skipped.append({
                        "signal_id": row.id,
                        "reason": f"Confidence {confidence}% below threshold {auto_threshold}%"
                    })

            # Session auto-commits on context manager exit

        return {
            "status": "completed",
            "tasks_created": len(created_tasks),
            "tasks_skipped": len(skipped),
            "errors": len(errors),
            "created": created_tasks,
            "skipped": skipped,
            "error_details": errors
        }

    def _signal_to_legion_task(self, signal: Dict) -> Dict[str, Any]:
        """Convert a signal to Legion task format."""
        signal_type = signal.get("type", "todo")
        severity = signal.get("severity", "medium")

        # Map severity to Legion priority (1=highest)
        priority_map = {
            "critical": 1,
            "high": 2,
            "medium": 3,
            "low": 4
        }

        # Generate title
        message = signal.get("message", "Enhancement task")[:80]
        title = f"[{signal_type.upper()}] {message}"

        # Generate description with context
        source_file = signal.get("source_file", "unknown")
        line_number = signal.get("line_number", "?")

        description = f"""Auto-generated from enhancement signal.

**Source:** `{source_file}:{line_number}`

**Signal:** {signal.get("message", "")}

**Context:**
```
{signal.get("context", "No context available")}
```

**Detected:** {signal.get("detected_at", "")}
**Confidence:** {signal.get("confidence", 0)}%
**Signal ID:** {signal.get("id", "")}
"""

        # Build prompt for Claude execution
        prompt = f"""Fix the following {signal_type.upper()} issue:

File: {source_file}
Line: {line_number}
Issue: {signal.get("message", "")}

Context:
{signal.get("context", "")}

Please analyze and fix this issue, then run any relevant tests."""

        return {
            "title": title,
            "description": description,
            "prompt": prompt,
            "priority": priority_map.get(severity, 3),
            "order": 0,  # Will be ordered by priority
            # Extended fields (if Legion has the ADA features migration)
            "story_points": self._estimate_points(severity, signal_type),
            "source": "enhancement_engine",
            "category": signal_type
        }

    def _estimate_points(self, severity: str, signal_type: str) -> int:
        """Estimate story points for a signal."""
        points_map = {
            ("critical", "security"): 13,
            ("critical", "fixme"): 8,
            ("high", "fixme"): 5,
            ("high", "todo"): 5,
            ("high", "security"): 8,
            ("medium", "todo"): 3,
            ("medium", "hack"): 5,
            ("medium", "fixme"): 3,
            ("low", "todo"): 2,
            ("low", "deprecated"): 2,
            ("low", "hack"): 3
        }
        return points_map.get((severity, signal_type), 3)

    @staticmethod
    def _row_to_dict(row: EnhancementSignalModel) -> Dict[str, Any]:
        """Convert an ORM row to a plain dict for helper methods."""
        return {
            "id": row.id,
            "type": row.type,
            "message": row.message,
            "severity": row.severity,
            "source_file": row.source_file,
            "line_number": row.line_number,
            "context": row.context,
            "status": row.status,
            "confidence": row.confidence,
            "impact_score": row.impact_score,
            "risk_score": row.risk_score,
            "priority_score": row.priority_score,
            "project_name": row.project_name,
            "detected_at": row.detected_at.isoformat() if row.detected_at else "",
            "converted_to_task": row.converted_to_task,
            "converted_to_legion_task": row.converted_to_legion_task,
            "converted_at": row.converted_at.isoformat() if row.converted_at else None,
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get enhancement system statistics using SQL aggregation."""
        async with get_session() as session:
            # Total count
            total_result = await session.execute(
                select(sa_func.count(EnhancementSignalModel.id))
            )
            total = total_result.scalar_one()

            # Counts by status
            status_result = await session.execute(
                select(
                    EnhancementSignalModel.status,
                    sa_func.count(EnhancementSignalModel.id),
                ).group_by(EnhancementSignalModel.status)
            )
            by_status_raw = {row[0]: row[1] for row in status_result.all()}
            by_status = {
                "pending": by_status_raw.get("pending", 0),
                "converted": by_status_raw.get("converted", 0),
                "dismissed": by_status_raw.get("dismissed", 0),
            }

            # Counts by type
            type_result = await session.execute(
                select(
                    EnhancementSignalModel.type,
                    sa_func.count(EnhancementSignalModel.id),
                ).group_by(EnhancementSignalModel.type)
            )
            by_type = {row[0]: row[1] for row in type_result.all()}

            # Counts by severity
            severity_result = await session.execute(
                select(
                    EnhancementSignalModel.severity,
                    sa_func.count(EnhancementSignalModel.id),
                ).group_by(EnhancementSignalModel.severity)
            )
            by_severity = {row[0]: row[1] for row in severity_result.all()}

            # Scan metadata from ServiceConfigModel
            cfg_result = await session.execute(
                select(ServiceConfigModel.config).where(
                    ServiceConfigModel.service_name == "enhancement"
                )
            )
            cfg = cfg_result.scalar_one_or_none() or {}

        return {
            "total_signals": total,
            "pending": by_status["pending"],
            "converted_to_tasks": by_status["converted"],
            "dismissed": by_status["dismissed"],
            "by_type": by_type,
            "by_severity": by_severity,
            "last_scan_at": cfg.get("lastScanAt"),
            "scan_count": cfg.get("scanCount", 0)
        }


@lru_cache()
def get_enhancement_service() -> EnhancementService:
    """Get cached enhancement service instance."""
    return EnhancementService()
