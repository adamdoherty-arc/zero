"""
Zero Company OS MCP connector.

This is the narrow MCP surface intended for Claude Co-Work / Claude Desktop:
task-first, docs-aware, and approval-aware. It intentionally avoids broad Zero
capabilities like email, content automation, trading, or robot control.

Default transport is local stdio. For Claude Co-Work remote connectors, run the
same server with streamable HTTP behind an authenticated tunnel.

Environment:
  ZERO_API_URL             default http://localhost:18792
  ZERO_GATEWAY_TOKEN       bearer token for Zero API
  ZERO_COMPANY_DOCS_ROOT   optional docs root override
  ZERO_COMPANY_MCP_HOST    HTTP host, default 127.0.0.1
  ZERO_COMPANY_MCP_PORT    HTTP port, default 8787
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()

API_URL = os.getenv("ZERO_API_URL", "http://localhost:18792").rstrip("/")
API_TOKEN = os.getenv("ZERO_GATEWAY_TOKEN") or os.getenv("ZERO_API_TOKEN", "")

HIGH_RISK_TERMS: dict[str, tuple[str, ...]] = {
    "purchase_or_subscription": (
        "buy",
        "purchase",
        "subscribe",
        "order",
        "pay",
        "card",
        "bank",
        "merchant",
        "stripe",
        "account change",
    ),
    "legal_or_llc": (
        "file llc",
        "sunbiz",
        "articles of organization",
        "ein",
        "operating agreement",
        "ip assignment",
        "registered agent",
        "tax election",
        "s-corp",
        "section 475",
        "contract",
        "terms of service",
        "privacy policy",
    ),
    "client_or_public": (
        "send client",
        "email client",
        "proposal",
        "sow",
        "publish",
        "website",
        "adamdoherty.com",
        "linkedin",
        "public",
    ),
    "security_or_infra": (
        "secret",
        "credential",
        "api key",
        "oauth",
        "production",
        "deploy",
        "domain",
        "dns",
    ),
    "financial": (
        "trade",
        "broker",
        "robinhood",
        "tradier",
        "transfer",
        "wire",
        "tax return",
        "deduction",
        "cpa file",
    ),
}


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    return headers


async def _request_json(
    method: Literal["GET", "POST", "PATCH"],
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method,
            f"{API_URL}{path}",
            headers=_headers(),
            params=params,
            json=body,
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {"text": resp.text}
    if resp.status_code >= 400:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "error": payload,
            "path": path,
        }
    return payload


def _docs_root() -> Path:
    candidates = [
        os.getenv("ZERO_COMPANY_DOCS_ROOT"),
        r"C:\code\zero\docs\company",
        "/projects/zero/docs/company",
        str(Path(__file__).resolve().parent.parent / "docs" / "company"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path.resolve()
    return (Path(__file__).resolve().parent.parent / "docs" / "company").resolve()


def _safe_doc_path(doc_path: str) -> Path:
    root = _docs_root()
    cleaned = doc_path.replace("\\", "/").strip().lstrip("/")
    if not cleaned.endswith(".md"):
        cleaned = f"{cleaned}.md"
    path = (root / cleaned).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("doc_path must stay inside docs/company") from exc
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Company doc not found: {cleaned}")
    return path


def _active_docs(include_archive: bool = False) -> list[Path]:
    root = _docs_root()
    docs: list[Path] = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root).as_posix()
        if not include_archive and (
            rel.startswith("_source-tree/") or rel.startswith("plans/archive/")
        ):
            continue
        docs.append(path)
    return sorted(docs, key=lambda p: p.relative_to(root).as_posix().lower())


def _title_for_doc(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def _excerpt(text: str, query: str, chars: int = 420) -> str:
    lower = text.lower()
    idx = lower.find(query.lower())
    if idx < 0:
        return text[:chars].strip()
    start = max(0, idx - chars // 3)
    end = min(len(text), idx + chars)
    return text[start:end].strip()


def classify_company_action(action: str) -> dict[str, Any]:
    """Classify whether an action needs human approval before execution."""
    haystack = action.lower()
    categories: list[str] = []
    matches: dict[str, list[str]] = {}
    for category, terms in HIGH_RISK_TERMS.items():
        hits = [term for term in terms if term in haystack]
        if hits:
            categories.append(category)
            matches[category] = hits
    return {
        "requires_approval": bool(categories),
        "categories": categories,
        "matches": matches,
        "policy": (
            "High-risk company actions require explicit approval records before "
            "execution: purchases, legal filings, tax elections, client/public "
            "communications, account changes, security changes, and financial actions."
        ),
    }


mcp = FastMCP(
    "zero-company-os",
    instructions=(
        "Use this connector for ADA AI LLC Company OS. You may read docs, "
        "summarize context, create/update internal tasks, and queue approvals. "
        "Do not directly execute purchases, filings, tax elections, client/public "
        "communications, account changes, security changes, or financial actions."
    ),
    host=os.getenv("ZERO_COMPANY_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("ZERO_COMPANY_MCP_PORT", "8787")),
    streamable_http_path="/mcp",
)


@mcp.tool()
async def company_operating_context() -> dict[str, Any]:
    """Return Zero's retrieval-friendly Company OS context."""
    return await _request_json("GET", "/api/company/operating-context")


@mcp.tool()
async def company_docs_index() -> list[dict[str, Any]] | dict[str, Any]:
    """List active Company OS docs with titles, summaries, paths, and timestamps."""
    return await _request_json("GET", "/api/company/docs-index")


@mcp.tool()
async def company_read_doc(doc_path: str) -> dict[str, Any]:
    """Read one markdown doc from docs/company, for example INDEX.md or task-backlog.md."""
    try:
        path = _safe_doc_path(doc_path)
        root = _docs_root()
        content = path.read_text(encoding="utf-8", errors="ignore")
        return {
            "ok": True,
            "title": _title_for_doc(path),
            "path": path.relative_to(root).as_posix(),
            "content": content,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
async def company_search_docs(
    query: str,
    limit: int = 8,
    include_archive: bool = False,
) -> dict[str, Any]:
    """Search Company OS docs by keyword and return concise excerpts."""
    root = _docs_root()
    results: list[dict[str, Any]] = []
    q = query.strip()
    if not q:
        return {"ok": False, "error": "query is required"}
    for path in _active_docs(include_archive=include_archive):
        text = path.read_text(encoding="utf-8", errors="ignore")
        occurrences = len(re.findall(re.escape(q), text, flags=re.IGNORECASE))
        if occurrences:
            results.append(
                {
                    "title": _title_for_doc(path),
                    "path": path.relative_to(root).as_posix(),
                    "occurrences": occurrences,
                    "excerpt": _excerpt(text, q),
                }
            )
    results.sort(key=lambda item: item["occurrences"], reverse=True)
    return {"ok": True, "query": query, "results": results[: max(1, min(limit, 30))]}


@mcp.tool()
async def company_guardrail_check(action: str) -> dict[str, Any]:
    """Check whether a proposed company action can be done directly or needs approval."""
    return classify_company_action(action)


@mcp.tool()
async def company_list_tasks(
    status: str | None = None,
    domain: str | None = None,
    owner_agent: str | None = None,
    filter_name: str | None = None,
    search: str | None = None,
    limit: int = 50,
    project_id: str = "company",
) -> Any:
    """List editable Company OS work items from Zero's canonical company task API."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    if status:
        params["status"] = status
    if domain:
        params["domain"] = domain
    if owner_agent:
        params["owner_agent"] = owner_agent
    if filter_name:
        params["filter_name"] = filter_name
    if search:
        params["search"] = search
    if project_id != "company":
        return {"ok": False, "error": "Zero Company MCP only exposes project_id=company work items."}
    return await _request_json("GET", "/api/company/work-items", params=params)


@mcp.tool()
async def company_create_task(
    title: str,
    description: str = "",
    priority: Literal["critical", "high", "medium", "low"] = "medium",
    category: Literal["bug", "feature", "enhancement", "chore", "documentation"] = "feature",
    project_id: str = "company",
    sprint_id: str | None = None,
    domain: str | None = None,
    owner_agent: str | None = None,
    due_at: str | None = None,
) -> Any:
    """Create an internal Company OS work item in Zero with server-side approval guardrails."""
    guardrail = classify_company_action(f"{title}\n{description}")
    if project_id != "company":
        return {"ok": False, "error": "Zero Company MCP only creates project_id=company work items."}
    body = {
        "title": title,
        "description": description,
        "project_id": project_id,
        "sprint_id": sprint_id,
        "priority": priority,
        "category": category,
        "source": "MANUAL",
        "source_reference": "zero-company-mcp",
        "domain": domain,
        "owner_agent": owner_agent,
        "due_at": due_at,
    }
    created = await _request_json("POST", "/api/company/work-items", body=body)
    return {"task": created, "guardrail": guardrail}


@mcp.tool()
async def company_update_task(
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    blocked_reason: str | None = None,
    domain: str | None = None,
    owner_agent: str | None = None,
    due_at: str | None = None,
    risk_level: str | None = None,
) -> Any:
    """Update a company work item. Done-state and high-risk changes stay approval-gated server-side."""
    body = {
        key: value
        for key, value in {
            "status": status,
            "title": title,
            "description": description,
            "priority": priority,
            "blocked_reason": blocked_reason,
            "domain": domain,
            "owner_agent": owner_agent,
            "due_at": due_at,
            "risk_level": risk_level,
        }.items()
        if value is not None
    }
    if not body:
        return {"ok": False, "error": "No updates provided"}
    return await _request_json("PATCH", f"/api/company/work-items/{task_id}", body=body)


@mcp.tool()
async def company_complete_task(
    task_id: str,
    completion_note: str = "",
    allow_high_risk_completion: bool = False,
) -> Any:
    """
    Mark a company work item done through Zero's approval-safe completion endpoint.

    High-risk work returns an approval-gated task state instead of bypassing the
    gate. The allow_high_risk_completion argument is accepted for compatibility
    but does not override Zero's guardrails.
    """
    task = await _request_json("GET", f"/api/company/work-items/{task_id}")
    if isinstance(task, dict) and task.get("ok") is False:
        return task
    guardrail = classify_company_action(
        f"{task.get('title', '')}\n{task.get('description', '')}\n{completion_note}"
    )
    if allow_high_risk_completion and guardrail["requires_approval"]:
        guardrail["note"] = "allow_high_risk_completion ignored; server guardrails remain authoritative."
    if completion_note:
        await _request_json(
            "PATCH",
            f"/api/company/work-items/{task_id}",
            body={
                "description": (
                    task.get("description") or ""
                )
                + f"\n\nCompletion note: {completion_note}",
            },
        )
    updated = await _request_json("POST", f"/api/company/work-items/{task_id}/complete", body={"actor": "claude-cowork"})
    return {
        "status": "approval_required" if isinstance(updated, dict) and updated.get("status") == "blocked" else "completed",
        "task": updated,
        "guardrail": guardrail,
    }


@mcp.tool()
async def company_queue_approval(
    title: str,
    description: str = "",
    request_type: str = "company_high_risk_action",
    route: str = "/company/approvals",
    context: dict[str, Any] | None = None,
    expires_in_hours: int = 72,
) -> Any:
    """Create a human approval record for high-risk company work."""
    return await _request_json(
        "POST",
        "/api/approvals",
        body={
            "request_type": request_type,
            "title": title,
            "description": description,
            "context_data": context or {},
            "initiated_by": "claude-cowork",
            "route": route,
            "expires_in_hours": expires_in_hours,
            "auto_action_on_expiry": "reject",
        },
    )


@mcp.tool()
async def company_list_approvals(status: str = "pending", limit: int = 50) -> dict[str, Any]:
    """List both legacy approvals and tiered agent approvals."""
    legacy_path = "/api/approvals/pending" if status == "pending" else "/api/approvals/all"
    legacy_params = {"limit": limit}
    if status != "pending":
        legacy_params["status"] = status
    agent_params = {"status": status, "limit": limit}
    legacy = await _request_json("GET", legacy_path, params=legacy_params)
    agent = await _request_json("GET", "/api/agent-approvals", params=agent_params)
    return {"legacy_approvals": legacy, "agent_approvals": agent}


@mcp.tool()
async def company_daily_brief(limit: int = 20) -> dict[str, Any]:
    """Return a concise operating brief: context, open tasks, approvals, and seed backlog fallback."""
    context = await company_operating_context()
    tasks = await company_list_tasks(limit=limit)
    approvals = await company_list_approvals(status="pending", limit=limit)
    operator = await company_operator_status()
    backlog_doc = await company_read_doc("task-backlog.md")
    return {
        "context": context,
        "tasks": tasks,
        "approvals": approvals,
        "operator": operator,
        "seed_backlog_available": bool(backlog_doc.get("ok")),
        "seed_backlog_excerpt": (
            backlog_doc.get("content", "")[:2500] if backlog_doc.get("ok") else None
        ),
    }


@mcp.tool()
async def company_operator_status() -> Any:
    """Return the live Zero Company Operator heartbeat and company state."""
    return await _request_json("GET", "/api/company/operator/status")


@mcp.tool()
async def company_operator_today() -> Any:
    """Return Zero's answer for what Adam should work on today."""
    return await _request_json("GET", "/api/company/operator/today")


@mcp.tool()
async def company_operator_overnight() -> Any:
    """Return the latest overnight report and recent overnight runs."""
    return await _request_json("GET", "/api/company/operator/overnight")


@mcp.tool()
async def company_operator_runs(
    run_type: str | None = None,
    limit: int = 20,
) -> Any:
    """List recent Company Operator runs."""
    params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
    if run_type:
        params["run_type"] = run_type
    return await _request_json("GET", "/api/company/operator/runs", params=params)


@mcp.tool()
async def company_operator_run_tick(
    run_type: Literal["manual", "monitor", "overnight", "formation"] = "manual",
    force: bool = False,
) -> Any:
    """
    Run one Company Operator tick.

    The operator can only perform internal work and approval queueing. It does
    not execute purchases, filings, legal/tax decisions, client/public messages,
    account changes, or financial actions.
    """
    return await _request_json(
        "POST",
        "/api/company/operator/tick",
        body={"run_type": run_type, "force": force, "requested_by": "claude-cowork"},
        timeout=60.0,
    )


@mcp.tool()
async def company_operator_generate_report(
    report_type: Literal["manual", "morning_brief", "evening_report", "weekly_review"] = "manual",
) -> Any:
    """Generate a Company Operator report now."""
    return await _request_json(
        "POST",
        "/api/company/operator/report",
        body={"report_type": report_type, "requested_by": "claude-cowork"},
        timeout=60.0,
    )


@mcp.tool()
async def company_operator_pause() -> Any:
    """Pause scheduled overnight work while keeping read-only status available."""
    return await _request_json("POST", "/api/company/operator/pause")


@mcp.tool()
async def company_operator_resume() -> Any:
    """Resume scheduled overnight work."""
    return await _request_json("POST", "/api/company/operator/resume")


@mcp.tool()
async def company_operator_assign_task(
    task_id: str,
    role_id: str,
) -> Any:
    """Assign a Zero company task to a company subagent as an internal work packet."""
    return await _request_json(
        "POST",
        "/api/company/operator/assign",
        body={"task_id": task_id, "role_id": role_id, "requested_by": "claude-cowork"},
    )


@mcp.tool()
async def company_operator_queue_approval(
    summary: str,
    tier: Literal["write_external", "financial"] = "write_external",
    tool_name: str = "claude_cowork_company_action",
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Queue a tiered approval for a high-risk company action."""
    return await _request_json(
        "POST",
        "/api/company/operator/approvals",
        body={
            "summary": summary,
            "tier": tier,
            "tool_name": tool_name,
            "arguments": arguments or {},
            "requested_by": "claude-cowork",
        },
    )


@mcp.tool()
async def company_seed_backlog_from_docs(
    dry_run: bool = True,
    max_tasks: int = 60,
) -> dict[str, Any]:
    """
    Parse docs/company/task-backlog.md and optionally create internal company tasks.

    Defaults to dry_run so Claude Co-Work can preview before writing records.
    """
    path = _safe_doc_path("task-backlog.md")
    tasks: list[dict[str, str]] = []
    current_sprint = "Company"
    in_frontmatter = False
    started_backlog = False
    for index, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines()):
        line = raw_line.strip()
        if index == 0 and line == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line == "---":
                in_frontmatter = False
            continue
        if line == "# Seed Task Backlog":
            started_backlog = True
            continue
        if not started_backlog:
            continue
        if line.startswith("## "):
            current_sprint = line[3:].strip()
            continue
        if not line.startswith("- "):
            continue
        title = line[2:].strip().rstrip(".")
        if not title:
            continue
        tasks.append(
            {
                "title": title,
                "description": f"Seeded from docs/company/task-backlog.md ({current_sprint}).",
                "priority": "high" if current_sprint == "Formation Sprint" else "medium",
                "category": "chore",
                "sprint": current_sprint,
            }
        )
    tasks = tasks[: max(1, min(max_tasks, 120))]
    if dry_run:
        seed_status = await _request_json("GET", "/api/company/work-items/seed-status")
        return {"dry_run": True, "count": len(tasks), "tasks": tasks, "seed_status": seed_status}
    imported = await _request_json(
        "POST",
        "/api/company/work-items/import-seed",
        body={"actor": "claude-cowork"},
    )
    return {"dry_run": False, "import": imported}


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero Company OS MCP connector")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=os.getenv("ZERO_COMPANY_MCP_TRANSPORT", "stdio"),
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
