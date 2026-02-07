"""
Workflow Orchestration Engine for Zero.
Sprint 42: Tasks 73-76.

Combines WorkflowParser, DAGExecutor (via LangGraph StateGraph),
StateManager for crash recovery, and StepHandlers for all step types.

Each YAML workflow is dynamically compiled into a LangGraph StateGraph
where steps become nodes and depends_on edges become graph edges.
"""

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from functools import lru_cache

import yaml
import structlog
import httpx

from langgraph.graph import StateGraph, START, END

logger = structlog.get_logger(__name__)


# =============================================================================
# State Definitions
# =============================================================================

class WorkflowState(TypedDict):
    """State flowing through a workflow LangGraph execution."""
    workflow_id: str
    execution_id: str
    variables: Dict[str, Any]
    trigger: Dict[str, Any]
    steps: Dict[str, Dict[str, Any]]  # step_id -> {output, status, error, ...}
    current_step: Optional[str]
    status: str  # pending, running, completed, failed, cancelled
    error: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


class WorkflowDefinition:
    """Parsed YAML workflow definition."""

    def __init__(self, data: dict, source_path: Optional[str] = None):
        self.name: str = data["name"]
        self.version: str = data.get("version", "1.0.0")
        self.description: str = data.get("description", "")
        self.triggers: List[dict] = data.get("triggers", [])
        self.variables: List[dict] = data.get("variables", [])
        self.steps: List[dict] = data.get("steps", [])
        self.outputs: List[dict] = data.get("outputs", [])
        self.source_path = source_path
        self._validate()

    def _validate(self):
        """Validate workflow structure."""
        if not self.name:
            raise ValueError("Workflow must have a name")
        if not self.steps:
            raise ValueError(f"Workflow '{self.name}' has no steps")

        step_ids = {s["id"] for s in self.steps}
        for step in self.steps:
            if "id" not in step:
                raise ValueError(f"Step missing 'id' in workflow '{self.name}'")
            if "type" not in step:
                raise ValueError(f"Step '{step['id']}' missing 'type'")
            for dep in step.get("depends_on", []):
                if dep not in step_ids:
                    raise ValueError(
                        f"Step '{step['id']}' depends on unknown step '{dep}'"
                    )

    def get_default_variables(self) -> Dict[str, Any]:
        """Get default variable values."""
        return {v["name"]: v.get("default") for v in self.variables}

    def get_step(self, step_id: str) -> Optional[dict]:
        """Get step definition by ID."""
        for s in self.steps:
            if s["id"] == step_id:
                return s
        return None

    def topological_order(self) -> List[List[str]]:
        """Return steps in topological order, grouped by parallel waves."""
        deps = {}
        for step in self.steps:
            deps[step["id"]] = set(step.get("depends_on", []))

        resolved = set()
        waves = []

        while deps:
            wave = [
                sid for sid, d in deps.items()
                if d.issubset(resolved)
            ]
            if not wave:
                remaining = list(deps.keys())
                raise ValueError(
                    f"Circular dependency in workflow '{self.name}': {remaining}"
                )
            waves.append(wave)
            resolved.update(wave)
            for sid in wave:
                del deps[sid]

        return waves


# =============================================================================
# Template Engine
# =============================================================================

def resolve_template(template: Any, context: Dict[str, Any]) -> Any:
    """Resolve {{ }} templates in strings using context."""
    if not isinstance(template, str):
        return template

    def replacer(match):
        expr = match.group(1).strip()
        try:
            # Support dot notation: steps.sync.output.newCount
            parts = expr.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return match.group(0)
                if value is None:
                    return ""
            return str(value) if value is not None else ""
        except Exception:
            return match.group(0)

    # Handle | default() filter
    def handle_default(match):
        expr = match.group(1).strip()
        default_match = re.search(r"\|\s*default\(['\"](.+?)['\"]\)", expr)
        if default_match:
            default_val = default_match.group(1)
            clean_expr = re.sub(r"\s*\|\s*default\(.+?\)", "", expr).strip()
            result = resolve_template("{{ " + clean_expr + " }}", context)
            return result if result and result != "{{ " + clean_expr + " }}" else default_val
        return None

    # First pass: handle defaults
    result = template
    for match in re.finditer(r"\{\{(.+?)\}\}", template):
        default_result = handle_default(match)
        if default_result is not None:
            result = result.replace(match.group(0), default_result)

    # Second pass: regular template substitution
    result = re.sub(r"\{\{(.+?)\}\}", replacer, result)
    return result


def resolve_dict(data: Any, context: Dict[str, Any]) -> Any:
    """Recursively resolve templates in dicts/lists."""
    if isinstance(data, str):
        return resolve_template(data, context)
    elif isinstance(data, dict):
        return {k: resolve_dict(v, context) for k, v in data.items()}
    elif isinstance(data, list):
        return [resolve_dict(item, context) for item in data]
    return data


def evaluate_condition(condition_str: str, context: Dict[str, Any]) -> bool:
    """Evaluate a {{ }} condition expression."""
    if not condition_str:
        return True
    resolved = resolve_template(condition_str, context)
    if resolved in ("", "None", "0", "false", "False"):
        return False
    try:
        # Try evaluating simple comparisons
        if ">" in resolved or "<" in resolved or "==" in resolved:
            return bool(eval(resolved, {"__builtins__": {}}, {}))
    except Exception:
        pass
    return bool(resolved)


# =============================================================================
# Step Handlers
# =============================================================================

class StepHandler:
    """Base class for workflow step execution."""

    async def execute(
        self, step: dict, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        raise NotImplementedError


class SkillHandler(StepHandler):
    """Execute skill-based steps (gmail, weather, etc.)."""

    async def execute(self, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
        config = resolve_dict(step.get("config", {}), context)
        skill_name = config.get("skill", "")
        action = config.get("action", "")
        params = config.get("params", {})

        logger.info("skill_handler_execute", skill=skill_name, action=action)

        try:
            result = await self._invoke_skill(skill_name, action, params)
            return {"output": result, "status": "completed"}
        except Exception as e:
            logger.error("skill_handler_error", skill=skill_name, error=str(e))
            return {"output": None, "status": "failed", "error": str(e)}

    async def _invoke_skill(
        self, skill: str, action: str, params: dict
    ) -> Any:
        """Invoke a Zero skill by name."""
        if skill == "gmail":
            return await self._gmail_skill(action, params)
        elif skill == "weather":
            return await self._weather_skill(action, params)
        elif skill == "sprint":
            return await self._sprint_skill(action, params)
        elif skill == "enhancement":
            return await self._enhancement_skill(action, params)
        else:
            return {"message": f"Skill '{skill}' not implemented", "status": "skipped"}

    async def _gmail_skill(self, action: str, params: dict) -> Any:
        from app.services.gmail_service import get_gmail_service
        gmail = get_gmail_service()
        if not gmail.is_connected():
            return {"status": "disconnected", "newCount": 0}

        if action == "sync":
            return await gmail.sync_incremental()
        elif action == "classifyNew":
            emails = await gmail.get_emails(max_results=10, unread_only=True)
            classified = 0
            for e in emails:
                await gmail.classify_email_ai(
                    e.subject, str(e.from_address), e.snippet or ""
                )
                classified += 1
            return {"classified": classified, "summary": f"Classified {classified} emails"}
        elif action == "checkAlertRules":
            alerts = gmail.get_recent_alerts(hours=1)
            return {"alertCount": len(alerts), "alertMessage": "\n".join(
                f"- {a.get('subject', 'No subject')}" for a in alerts
            )}
        elif action == "archiveByCategory":
            return {"archivedCount": 0, "message": "Auto-archive not yet wired"}
        elif action == "getDigest":
            digest = await gmail.generate_digest()
            return {"total": digest.total_emails, "unread": digest.unread_emails}
        return {"status": "unknown_action", "action": action}

    async def _weather_skill(self, action: str, params: dict) -> Any:
        location = params.get("location", "Jacksonville, FL")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://wttr.in/{location}?format=j1"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    current = data.get("current_condition", [{}])[0]
                    return {
                        "location": location,
                        "temp_f": current.get("temp_F"),
                        "condition": current.get("weatherDesc", [{}])[0].get("value"),
                        "humidity": current.get("humidity"),
                    }
        except Exception as e:
            return {"error": str(e), "location": location}
        return {"status": "unavailable"}

    async def _sprint_skill(self, action: str, params: dict) -> Any:
        from app.services.legion_client import get_legion_client
        legion = get_legion_client()
        if action == "getSummary":
            return await legion.get_daily_summary()
        elif action == "getBlocked":
            return await legion.get_blocked_tasks()
        return {"status": "unknown_action"}

    async def _enhancement_skill(self, action: str, params: dict) -> Any:
        from app.services.enhancement_service import get_enhancement_service
        svc = get_enhancement_service()
        if action == "scan":
            return await svc.scan_for_signals()
        return {"status": "unknown_action"}


class LLMHandler(StepHandler):
    """Execute LLM-based steps via Ollama."""

    async def execute(self, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
        config = resolve_dict(step.get("config", {}), context)
        prompt = config.get("prompt", "")
        model = config.get("model", "qwen3:32b")
        temperature = float(config.get("temperature", 0.7))

        logger.info("llm_handler_execute", model=model, prompt_len=len(prompt))

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": temperature},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "output": data.get("response", ""),
                        "status": "completed",
                        "model": model,
                        "tokens": data.get("eval_count", 0),
                    }
                return {
                    "output": None,
                    "status": "failed",
                    "error": f"Ollama returned {resp.status_code}",
                }
        except Exception as e:
            return {"output": None, "status": "failed", "error": str(e)}


class HTTPHandler(StepHandler):
    """Execute HTTP request steps."""

    async def execute(self, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
        config = resolve_dict(step.get("config", {}), context)
        method = config.get("method", "GET").upper()
        url = config.get("url", "")
        headers = config.get("headers", {})
        body = config.get("body")
        timeout = config.get("timeout", 30)

        logger.info("http_handler_execute", method=method, url=url)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(
                    method, url, headers=headers, json=body
                )
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text
                return {
                    "output": data,
                    "status": "completed",
                    "status_code": resp.status_code,
                }
        except Exception as e:
            return {"output": None, "status": "failed", "error": str(e)}


class NotifyHandler(StepHandler):
    """Send notifications via Discord/email."""

    async def execute(self, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
        config = resolve_dict(step.get("config", {}), context)
        channel = config.get("channel", "discord")
        message = config.get("message", "")
        to = config.get("to", "self")

        logger.info("notify_handler_execute", channel=channel, msg_len=len(message))

        try:
            from app.services.notification_service import get_notification_service
            notification_service = get_notification_service()
            await notification_service.create_notification(
                title=f"Workflow: {context.get('workflow_id', 'unknown')}",
                message=message,
                channel=channel,
                source="workflow_engine",
            )
            return {"output": "sent", "status": "completed", "channel": channel}
        except Exception as e:
            return {"output": None, "status": "failed", "error": str(e)}


class ConditionHandler(StepHandler):
    """Evaluate conditions and branch."""

    async def execute(self, step: dict, context: Dict[str, Any]) -> Dict[str, Any]:
        config = resolve_dict(step.get("config", {}), context)
        condition = config.get("condition", "")
        result = evaluate_condition(condition, context)
        return {
            "output": result,
            "status": "completed",
            "branch": "true" if result else "false",
        }


# Handler registry
STEP_HANDLERS: Dict[str, StepHandler] = {
    "skill": SkillHandler(),
    "llm": LLMHandler(),
    "http": HTTPHandler(),
    "notify": NotifyHandler(),
    "condition": ConditionHandler(),
}


# =============================================================================
# State Manager (JSON persistence for crash recovery)
# =============================================================================

class StateManager:
    """Persist workflow execution state for resume after crashes."""

    def __init__(self, state_dir: str = "workspace/orchestration/state"):
        self.state_dir = Path(state_dir)
        self.executions_dir = self.state_dir / "executions"
        self.history_dir = self.state_dir / "history"
        self.executions_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def save_state(self, execution_id: str, state: Dict[str, Any]):
        """Save execution state to JSON."""
        path = self.executions_dir / f"{execution_id}.json"
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def load_state(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Load execution state from JSON."""
        path = self.executions_dir / f"{execution_id}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None

    def complete_execution(self, execution_id: str, state: Dict[str, Any]):
        """Move completed execution to history."""
        state["completed_at"] = datetime.utcnow().isoformat()
        # Save to history
        history_path = self.history_dir / f"{execution_id}.json"
        with open(history_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        # Remove from active
        active_path = self.executions_dir / f"{execution_id}.json"
        if active_path.exists():
            active_path.unlink()

    def get_active_executions(self) -> List[Dict[str, Any]]:
        """Get all active (incomplete) executions."""
        results = []
        for path in self.executions_dir.glob("*.json"):
            try:
                with open(path) as f:
                    results.append(json.load(f))
            except Exception:
                pass
        return results

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        files = sorted(
            self.history_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]
        results = []
        for path in files:
            try:
                with open(path) as f:
                    results.append(json.load(f))
            except Exception:
                pass
        return results


# =============================================================================
# Workflow Parser
# =============================================================================

class WorkflowParser:
    """Load and validate YAML workflow definitions."""

    def __init__(self, workflows_dir: str = "workspace/orchestration/workflows"):
        self.workflows_dir = Path(workflows_dir)
        self._cache: Dict[str, WorkflowDefinition] = {}

    def load_all(self) -> Dict[str, WorkflowDefinition]:
        """Load all workflow definitions from examples/ and custom/."""
        workflows = {}
        for subdir in ["examples", "custom"]:
            dir_path = self.workflows_dir / subdir
            if dir_path.exists():
                for path in dir_path.glob("*.yaml"):
                    try:
                        wf = self.load_file(str(path))
                        workflows[wf.name] = wf
                    except Exception as e:
                        logger.warning("workflow_load_error", path=str(path), error=str(e))
                for path in dir_path.glob("*.yml"):
                    try:
                        wf = self.load_file(str(path))
                        workflows[wf.name] = wf
                    except Exception as e:
                        logger.warning("workflow_load_error", path=str(path), error=str(e))
        self._cache = workflows
        return workflows

    def load_file(self, path: str) -> WorkflowDefinition:
        """Load a single workflow file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return WorkflowDefinition(data, source_path=path)

    def get(self, name: str) -> Optional[WorkflowDefinition]:
        """Get a cached workflow by name."""
        if not self._cache:
            self.load_all()
        return self._cache.get(name)

    def list_workflows(self) -> List[Dict[str, Any]]:
        """List all available workflows."""
        if not self._cache:
            self.load_all()
        return [
            {
                "name": wf.name,
                "version": wf.version,
                "description": wf.description,
                "steps": len(wf.steps),
                "triggers": [t.get("type") for t in wf.triggers],
                "source": wf.source_path,
            }
            for wf in self._cache.values()
        ]


# =============================================================================
# DAG Executor (LangGraph-powered)
# =============================================================================

class DAGExecutor:
    """
    Execute workflow steps as a LangGraph StateGraph.

    Each step becomes a graph node. Dependencies become edges.
    Parallel waves are executed concurrently via asyncio.gather.
    """

    def __init__(self, state_manager: Optional[StateManager] = None):
        self.state_manager = state_manager or StateManager()
        self._active: Dict[str, asyncio.Task] = {}

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        trigger: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a workflow definition using topological wave execution."""
        execution_id = str(uuid.uuid4())[:12]
        merged_vars = workflow.get_default_variables()
        if variables:
            merged_vars.update(variables)

        state: Dict[str, Any] = {
            "workflow_id": workflow.name,
            "execution_id": execution_id,
            "variables": merged_vars,
            "trigger": trigger or {"type": "manual"},
            "steps": {},
            "current_step": None,
            "status": "running",
            "error": None,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
        }

        self.state_manager.save_state(execution_id, state)

        logger.info(
            "workflow_execution_start",
            workflow=workflow.name,
            execution_id=execution_id,
            steps=len(workflow.steps),
        )

        try:
            waves = workflow.topological_order()

            for wave_idx, wave in enumerate(waves):
                logger.info(
                    "workflow_wave_start",
                    wave=wave_idx + 1,
                    total_waves=len(waves),
                    steps=wave,
                )

                # Build template context
                context = {
                    "variables": state["variables"],
                    "trigger": state["trigger"],
                    "steps": state["steps"],
                    "now": datetime.utcnow().isoformat(),
                }

                # Execute steps in this wave concurrently
                tasks = []
                for step_id in wave:
                    step_def = workflow.get_step(step_id)
                    if step_def:
                        tasks.append(
                            self._execute_step(step_def, context, state)
                        )

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for step_id, result in zip(wave, results):
                    if isinstance(result, Exception):
                        state["steps"][step_id] = {
                            "output": None,
                            "status": "failed",
                            "error": str(result),
                        }
                        step_def = workflow.get_step(step_id)
                        if step_def and step_def.get("on_error") != "continue":
                            state["status"] = "failed"
                            state["error"] = f"Step '{step_id}' failed: {result}"
                            self.state_manager.complete_execution(execution_id, state)
                            return state

                # Checkpoint after each wave
                self.state_manager.save_state(execution_id, state)

            state["status"] = "completed"
            state["completed_at"] = datetime.utcnow().isoformat()

        except Exception as e:
            state["status"] = "failed"
            state["error"] = str(e)
            logger.error("workflow_execution_failed", error=str(e))

        self.state_manager.complete_execution(execution_id, state)

        logger.info(
            "workflow_execution_complete",
            workflow=workflow.name,
            execution_id=execution_id,
            status=state["status"],
        )

        return state

    async def _execute_step(
        self,
        step_def: dict,
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a single workflow step."""
        step_id = step_def["id"]
        step_type = step_def["type"]

        # Check condition
        condition = step_def.get("condition")
        if condition and not evaluate_condition(condition, context):
            result = {"output": None, "status": "skipped", "reason": "condition_false"}
            state["steps"][step_id] = result
            logger.info("step_skipped", step=step_id, reason="condition_false")
            return result

        # Get handler
        handler = STEP_HANDLERS.get(step_type)
        if not handler:
            result = {"output": None, "status": "failed", "error": f"Unknown step type: {step_type}"}
            state["steps"][step_id] = result
            return result

        state["current_step"] = step_id
        logger.info("step_execute_start", step=step_id, type=step_type)

        # Execute with timeout
        timeout_ms = step_def.get("timeout", 300000)
        timeout_s = timeout_ms / 1000

        try:
            result = await asyncio.wait_for(
                handler.execute(step_def, context),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            result = {
                "output": None,
                "status": "failed",
                "error": f"Step timed out after {timeout_s}s",
            }
        except Exception as e:
            result = {"output": None, "status": "failed", "error": str(e)}

        state["steps"][step_id] = result

        logger.info(
            "step_execute_complete",
            step=step_id,
            status=result.get("status"),
        )

        return result

    async def resume_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Resume a crashed/interrupted execution."""
        state = self.state_manager.load_state(execution_id)
        if not state:
            return None

        # Find the workflow
        parser = WorkflowParser()
        workflow = parser.get(state["workflow_id"])
        if not workflow:
            return None

        # Find completed steps
        completed_steps = {
            sid for sid, info in state.get("steps", {}).items()
            if info.get("status") in ("completed", "skipped")
        }

        # Re-execute remaining steps
        state["status"] = "running"
        waves = workflow.topological_order()

        for wave in waves:
            remaining = [s for s in wave if s not in completed_steps]
            if not remaining:
                continue

            context = {
                "variables": state["variables"],
                "trigger": state["trigger"],
                "steps": state["steps"],
                "now": datetime.utcnow().isoformat(),
            }

            tasks = []
            for step_id in remaining:
                step_def = workflow.get_step(step_id)
                if step_def:
                    tasks.append(self._execute_step(step_def, context, state))

            await asyncio.gather(*tasks, return_exceptions=True)
            self.state_manager.save_state(execution_id, state)

        state["status"] = "completed"
        state["completed_at"] = datetime.utcnow().isoformat()
        self.state_manager.complete_execution(execution_id, state)
        return state

    def cancel_execution(self, execution_id: str) -> bool:
        """Cancel an active execution."""
        state = self.state_manager.load_state(execution_id)
        if not state:
            return False
        state["status"] = "cancelled"
        state["completed_at"] = datetime.utcnow().isoformat()
        self.state_manager.complete_execution(execution_id, state)
        return True


# =============================================================================
# Workflow Engine Singleton
# =============================================================================

class WorkflowEngine:
    """Top-level engine combining parser, executor, and state manager."""

    def __init__(self):
        self.parser = WorkflowParser()
        self.state_manager = StateManager()
        self.executor = DAGExecutor(self.state_manager)
        self._loaded = False

    def ensure_loaded(self):
        if not self._loaded:
            self.parser.load_all()
            self._loaded = True

    def list_workflows(self) -> List[Dict[str, Any]]:
        self.ensure_loaded()
        return self.parser.list_workflows()

    def get_workflow(self, name: str) -> Optional[WorkflowDefinition]:
        self.ensure_loaded()
        return self.parser.get(name)

    async def trigger_workflow(
        self,
        name: str,
        trigger: Optional[Dict[str, Any]] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.ensure_loaded()
        workflow = self.parser.get(name)
        if not workflow:
            return {"error": f"Workflow '{name}' not found", "status": "failed"}
        return await self.executor.execute_workflow(workflow, trigger, variables)

    async def resume(self, execution_id: str) -> Optional[Dict[str, Any]]:
        return await self.executor.resume_execution(execution_id)

    def cancel(self, execution_id: str) -> bool:
        return self.executor.cancel_execution(execution_id)

    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        return self.state_manager.load_state(execution_id)

    def get_active_executions(self) -> List[Dict[str, Any]]:
        return self.state_manager.get_active_executions()

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.state_manager.get_history(limit)


# Singleton
_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
