"""
Zero Backend MCP Server — exposes Zero's REST API as MCP tools.

Runs as a stdio MCP server. Claude calls these tools to interact with
Zero's backend (sprints, tasks, email, calendar, knowledge, etc.).

Environment variables:
  ZERO_API_URL   - Backend URL (default: http://localhost:18792)
  ZERO_API_TOKEN - Bearer token for authentication
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types


def _load_dotenv():
    """Load .env from project root (no dependency needed)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not os.getenv(key):  # Don't override existing env vars
            os.environ[key] = value


_load_dotenv()

server = Server("zero-api")

API_URL = os.getenv("ZERO_API_URL", "http://localhost:18792")
API_TOKEN = os.getenv("ZERO_GATEWAY_TOKEN", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }


async def _get(path: str, params: dict | None = None) -> str:
    """GET request to Zero backend, returns JSON string."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{API_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, default=str)


async def _post(path: str, body: dict | None = None) -> str:
    """POST request to Zero backend, returns JSON string."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{API_URL}{path}", headers=_headers(), json=body or {})
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, default=str)


async def _patch(path: str, body: dict | None = None) -> str:
    """PATCH request to Zero backend, returns JSON string."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.patch(f"{API_URL}{path}", headers=_headers(), json=body or {})
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2, default=str)


TOOLS = [
    types.Tool(
        name="get_sprints",
        description="List sprints. Optionally filter by status (active/completed/planned) and limit results.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: active, completed, planned"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    ),
    types.Tool(
        name="get_tasks",
        description="List tasks. Filter by sprint_id, status (todo/in_progress/done/blocked), or assignee.",
        inputSchema={
            "type": "object",
            "properties": {
                "sprint_id": {"type": "integer", "description": "Filter by sprint ID"},
                "status": {"type": "string", "description": "Filter: todo, in_progress, done, blocked"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    ),
    types.Tool(
        name="create_task",
        description="Create a new task in a sprint.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "sprint_id": {"type": "integer", "description": "Sprint to add task to"},
                "priority": {"type": "string", "description": "Priority: low, medium, high, critical"},
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="update_task",
        description="Update a task's status, title, or description.",
        inputSchema={
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID to update"},
                "status": {"type": "string", "description": "New status: todo, in_progress, done, blocked"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
            },
            "required": ["task_id"],
        },
    ),
    types.Tool(
        name="search_emails",
        description="Search Gmail cache for emails matching a query.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="get_email_digest",
        description="Get today's email digest summary.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_calendar_events",
        description="Get upcoming calendar events. Optionally specify days ahead.",
        inputSchema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days ahead to look (default 7)"},
            },
        },
    ),
    types.Tool(
        name="get_briefing",
        description="Get a comprehensive briefing combining sprints, email, calendar, and tasks.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="search_knowledge",
        description="Search notes and knowledge base. Supports semantic search.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="save_note",
        description="Save a note to the knowledge base.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Note content"},
                "category": {"type": "string", "description": "Category: general, project, personal, reference"},
            },
            "required": ["title", "content"],
        },
    ),
    types.Tool(
        name="get_research_topics",
        description="List research topics and findings.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: active, completed, paused"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    ),
    types.Tool(
        name="get_money_ideas",
        description="List income generation ideas and their status.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: new, researching, validated, rejected"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        },
    ),
    types.Tool(
        name="search_notion",
        description="Search Notion workspace for pages and content.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="system_status",
        description="Get Zero system status including service health, circuit breakers, and uptime.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="scheduler_status",
        description="Get scheduler job statuses, next run times, and recent execution results.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="tiktok_pipeline_status",
        description="Get TikTok Shop pipeline status including products, content queue, and research.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="tiktok_list_products",
        description="List TikTok Shop products. Filter by status, niche, product_type, min opportunity score.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: discovered, pending_approval, approved, researched, content_planned, active, rejected"},
                "niche": {"type": "string", "description": "Filter by niche category"},
                "product_type": {"type": "string", "description": "Filter: affiliate, dropship, own, unknown"},
                "min_score": {"type": "number", "description": "Minimum opportunity score (0-100)"},
                "search": {"type": "string", "description": "Search product names"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    ),
    types.Tool(
        name="tiktok_get_product",
        description="Get full details for a single TikTok Shop product including scores, sourcing, and content info.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Product ID"},
            },
            "required": ["product_id"],
        },
    ),
    types.Tool(
        name="tiktok_add_product",
        description="Add a product to TikTok Shop and auto-run research. Provide a name and optional details.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product name (e.g. 'LED Face Mask', 'Portable Blender')"},
                "niche": {"type": "string", "description": "Product niche (beauty, kitchen, tech, fitness, fashion, home, pet)"},
                "description": {"type": "string", "description": "Product description"},
                "product_type": {"type": "string", "description": "affiliate, dropship, or own"},
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="tiktok_import_url",
        description="Import a product from a URL (Amazon, AliExpress, TikTok Shop, etc.) and auto-research it.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Product URL to import"},
                "research": {"type": "boolean", "description": "Auto-run research after import (default true)"},
            },
            "required": ["url"],
        },
    ),
    types.Tool(
        name="tiktok_research_product",
        description="Trigger deep research on a product: SearXNG search, LLM scoring, market data estimation.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Product ID to research"},
            },
            "required": ["product_id"],
        },
    ),
    types.Tool(
        name="tiktok_enrich_product",
        description="Enrich a product with images, supplier info, success rating, and sourcing links.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Product ID to enrich"},
            },
            "required": ["product_id"],
        },
    ),
    types.Tool(
        name="tiktok_approve_products",
        description="Approve products for content creation. Moves them from pending to approved status.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_ids": {"type": "array", "items": {"type": "string"}, "description": "List of product IDs to approve"},
            },
            "required": ["product_ids"],
        },
    ),
    types.Tool(
        name="tiktok_reject_products",
        description="Reject products with a reason. Removes them from the pipeline.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_ids": {"type": "array", "items": {"type": "string"}, "description": "List of product IDs to reject"},
                "reason": {"type": "string", "description": "Reason for rejection"},
            },
            "required": ["product_ids"],
        },
    ),
    types.Tool(
        name="tiktok_generate_script",
        description="Generate a faceless video script for a product. Templates: voiceover_broll, text_overlay_showcase, before_after, listicle_topn, problem_solution.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Product ID to generate script for"},
                "template_type": {"type": "string", "description": "Template: voiceover_broll, text_overlay_showcase, before_after, listicle_topn, problem_solution"},
            },
            "required": ["product_id"],
        },
    ),
    types.Tool(
        name="tiktok_generate_ideas",
        description="Generate content ideas (hooks, scripts, captions) for a product using AI.",
        inputSchema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Product ID to generate ideas for"},
            },
            "required": ["product_id"],
        },
    ),
    types.Tool(
        name="tiktok_get_stats",
        description="Get TikTok Shop pipeline statistics: product counts by status, content queue stats, research cycle info.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="tiktok_run_pipeline",
        description="Run the TikTok pipeline. Modes: full (all steps), research_only, content_only, performance_only.",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "description": "Pipeline mode: full, research_only, content_only, performance_only (default: full)"},
            },
        },
    ),
    types.Tool(
        name="trigger_workflow",
        description="Trigger a named workflow.",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_name": {"type": "string", "description": "Workflow to trigger"},
                "params": {"type": "object", "description": "Workflow parameters"},
            },
            "required": ["workflow_name"],
        },
    ),
    types.Tool(
        name="invoke_orchestrator",
        description="Send a message to the Zero LangGraph orchestrator for complex multi-step processing. Use this for queries that need multiple services or intelligent routing.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message/query to process"},
                "thread_id": {"type": "string", "description": "Conversation thread ID for continuity"},
            },
            "required": ["message"],
        },
    ),
    types.Tool(
        name="vault_search",
        description="Hybrid BM25 + dense vector search over the indexed Obsidian vault. Returns top chunks with file paths and heading context. Use partitions=['reference'|'projects'|'journal'|'inbox'] to narrow — journal queries carry time-decay automatically.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language query"},
                "partitions": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["reference", "projects", "journal", "inbox"]},
                    "description": "Optional partition filter. Omit for all.",
                },
                "top_k": {"type": "integer", "default": 8, "minimum": 1, "maximum": 30},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="vault_get_file",
        description="Fetch the concatenated content of a single vault note by path (e.g. '30_Efforts/34_Zero/README.md'). Returns frontmatter, tags, and reassembled body from indexed chunks.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside the vault"},
            },
            "required": ["path"],
        },
    ),
    types.Tool(
        name="vault_propose_write",
        description="Write a markdown file under the agent-owned 00_Meta/_agent/** namespace. Use for proposals + drafts the human can later promote. Never touches human-owned notes — for those, use the cyanheads Obsidian MCP.",
        inputSchema={
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Relative path under 00_Meta/_agent/**"},
                "content": {"type": "string"},
                "source": {"type": "string", "default": "agent"},
            },
            "required": ["relative_path", "content"],
        },
    ),
    types.Tool(
        name="list_agent_approvals",
        description="List Zero's agent tool-call approval queue (tier-based: read|write_local|write_external|financial). Use status='pending' to surface what's waiting on a decision.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    # ---- Sight (wearable-agnostic vision) — Phase 6 ----
    types.Tool(
        name="list_sight_providers",
        description="List every registered SightProvider (reachy, meta_rayban, …) with status: active, last_frame_ts, width/height, backend/extra. Use this to know whether ambient vision data is currently available.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="get_sight_frame",
        description="Return the latest JPEG frame from a SightProvider as base64. Defaults to the active provider. Use this when you need to reason about what the user is currently seeing.",
        inputSchema={
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "Provider id, e.g. 'reachy' or 'meta_rayban'. Omit to use active."},
            },
        },
    ),
    types.Tool(
        name="describe_scene",
        description="Run VLM scene description on the active (or specified) SightProvider's latest frame. Optional `question` is answered grounded in the image. Returns {caption, actionable, answer, detections, provider}.",
        inputSchema={
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "question": {"type": "string", "description": "Optional question to answer about the scene."},
                "kind": {"type": "string", "enum": ["face", "hands"], "default": "face"},
            },
        },
    ),
    types.Tool(
        name="recent_sight_observations",
        description="Pull recent ambient-vision observations from the Obsidian vault (`00_Meta/_agent/vision/`). Use when the user asks 'what have I seen today' or 'summarize my day visually'.",
        inputSchema={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "default": 24, "description": "Lookback window in hours."},
                "limit": {"type": "integer", "default": 40},
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
    args = arguments or {}

    try:
        if name == "get_sprints":
            params = {}
            if "status" in args:
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/sprints", params or None)

        elif name == "get_tasks":
            params = {}
            if "sprint_id" in args:
                params["sprint_id"] = args["sprint_id"]
            if "status" in args:
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/tasks", params or None)

        elif name == "create_task":
            result = await _post("/api/tasks", args)

        elif name == "update_task":
            task_id = args.pop("task_id")
            result = await _patch(f"/api/tasks/{task_id}", args)

        elif name == "search_emails":
            params = {"q": args["query"]}
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/email/search", params)

        elif name == "get_email_digest":
            result = await _get("/api/email/digest")

        elif name == "get_calendar_events":
            params = {}
            if "days" in args:
                params["days"] = args["days"]
            result = await _get("/api/calendar/events", params or None)

        elif name == "get_briefing":
            result = await _get("/api/assistant/briefing")

        elif name == "search_knowledge":
            params = {"q": args["query"]}
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/knowledge/search", params)

        elif name == "save_note":
            result = await _post("/api/knowledge/notes", args)

        elif name == "get_research_topics":
            params = {}
            if "status" in args:
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/research/topics", params or None)

        elif name == "get_money_ideas":
            params = {}
            if "status" in args:
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/money-maker", params or None)

        elif name == "search_notion":
            result = await _get("/api/notion/search", {"q": args["query"]})

        elif name == "system_status":
            result = await _get("/api/system/status")

        elif name == "scheduler_status":
            result = await _get("/api/system/scheduler/status")

        elif name == "tiktok_pipeline_status":
            result = await _get("/api/tiktok-shop/pipeline-status")

        elif name == "tiktok_list_products":
            params = {}
            for key in ("status", "niche", "product_type", "min_score", "search", "limit"):
                if key in args:
                    params[key] = args[key]
            result = await _get("/api/tiktok-shop/products", params or None)

        elif name == "tiktok_get_product":
            result = await _get(f"/api/tiktok-shop/products/{args['product_id']}")

        elif name == "tiktok_add_product":
            result = await _post("/api/tiktok-shop/products/add-and-research", args)

        elif name == "tiktok_import_url":
            params = {"url": args["url"]}
            if "research" in args:
                params["research"] = args["research"]
            result = await _post("/api/tiktok-shop/products/import-url", params)

        elif name == "tiktok_research_product":
            result = await _post(f"/api/tiktok-shop/products/{args['product_id']}/research")

        elif name == "tiktok_enrich_product":
            result = await _post(f"/api/tiktok-shop/products/{args['product_id']}/enrich")

        elif name == "tiktok_approve_products":
            result = await _post("/api/tiktok-shop/products/approve", {"product_ids": args["product_ids"]})

        elif name == "tiktok_reject_products":
            body = {"product_ids": args["product_ids"]}
            if "reason" in args:
                body["reason"] = args["reason"]
            result = await _post("/api/tiktok-shop/products/reject", body)

        elif name == "tiktok_generate_script":
            body = {"product_id": args["product_id"]}
            if "template_type" in args:
                body["template_type"] = args["template_type"]
            result = await _post("/api/tiktok-content/scripts/generate", body)

        elif name == "tiktok_generate_ideas":
            result = await _post(f"/api/tiktok-shop/products/{args['product_id']}/ideas")

        elif name == "tiktok_get_stats":
            result = await _get("/api/tiktok-shop/stats")

        elif name == "tiktok_run_pipeline":
            params = {}
            if "mode" in args:
                params["mode"] = args["mode"]
            result = await _post("/api/tiktok-shop/pipeline/run", params)

        elif name == "trigger_workflow":
            body = {"name": args["workflow_name"]}
            if "params" in args:
                body["params"] = args["params"]
            result = await _post("/api/workflows/trigger", body)

        elif name == "vault_search":
            body: dict[str, Any] = {"query": args["query"], "top_k": args.get("top_k", 8)}
            if args.get("partitions"):
                body["partitions"] = args["partitions"]
            result = await _post("/api/vault/search", body)

        elif name == "vault_get_file":
            result = await _get("/api/vault/file", {"path": args["path"]})

        elif name == "vault_propose_write":
            result = await _post("/api/vault/propose", {
                "relative_path": args["relative_path"],
                "content": args["content"],
                "source": args.get("source", "agent"),
            })

        elif name == "list_agent_approvals":
            params = {}
            if "status" in args:
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = args["limit"]
            result = await _get("/api/agent-approvals", params or None)

        elif name == "invoke_orchestrator":
            body = {"message": args["message"]}
            if "thread_id" in args:
                body["thread_id"] = args["thread_id"]
            result = await _post("/api/orchestrator/graph/invoke", body)

        # ---- Sight tools (Phase 6) ----

        elif name == "list_sight_providers":
            result = await _get("/api/sight/providers")

        elif name == "get_sight_frame":
            provider_id = args.get("provider")
            path = (
                f"/api/sight/{provider_id}/frame.jpg"
                if provider_id
                else "/api/sight/active"  # active status; frame comes from /active-frame
            )
            # When no provider is specified, pull the active id first then fetch its frame.
            if not provider_id:
                import json as _json
                status = await _get("/api/sight/active")
                try:
                    provider_id = _json.loads(status).get("provider")
                except Exception:
                    provider_id = None
                if not provider_id:
                    result = json.dumps({"error": "no active sight provider"}, indent=2)
                else:
                    path = f"/api/sight/{provider_id}/frame.jpg"
            if provider_id:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(f"{API_URL}{path}", headers=_headers())
                if resp.status_code >= 400:
                    result = json.dumps({"error": f"frame fetch failed {resp.status_code}", "body": resp.text[:300]}, indent=2)
                else:
                    import base64 as _b64
                    result = json.dumps({
                        "provider": provider_id,
                        "bytes": len(resp.content),
                        "mime": resp.headers.get("content-type", "image/jpeg"),
                        "b64": _b64.b64encode(resp.content).decode("ascii"),
                    }, indent=2)

        elif name == "describe_scene":
            params: dict[str, Any] = {}
            if args.get("provider"):
                params["provider_id"] = args["provider"]
            if args.get("kind"):
                params["kind"] = args["kind"]
            if args.get("question"):
                params["question"] = args["question"]
            # POST /reachy/vision/scene takes query params only.
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{API_URL}/api/reachy/vision/scene",
                    headers=_headers(),
                    params=params,
                )
            if resp.status_code >= 400:
                result = json.dumps({"error": f"scene failed {resp.status_code}", "body": resp.text[:300]}, indent=2)
            else:
                result = json.dumps(resp.json(), indent=2, default=str)

        elif name == "recent_sight_observations":
            hours = int(args.get("hours", 24))
            limit = int(args.get("limit", 40))
            # Use vault_search with a broad query scoped to the agent vision folder.
            result = await _post(
                "/api/vault/search",
                {
                    "query": "vision-observation",
                    "top_k": limit,
                    "partitions": ["_agent"],
                },
            )
            # Callers can filter by date client-side; we pass `hours` through
            # as context so the LLM knows the window asked for.
            import json as _json
            try:
                parsed = _json.loads(result)
                parsed["_window_hours"] = hours
                result = json.dumps(parsed, indent=2, default=str)
            except Exception:
                pass

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

        return [types.TextContent(type="text", text=result)]

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500] if e.response else "No response body"
        return [types.TextContent(
            type="text",
            text=f"API error {e.response.status_code}: {error_body}",
        )]
    except httpx.ConnectError:
        return [types.TextContent(
            type="text",
            text=f"Cannot connect to Zero backend at {API_URL}. Is zero-api running?",
        )]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
