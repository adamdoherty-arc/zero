#!/usr/bin/env python
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.0"]
# ///
"""Token-light CLI dispatcher for any configured stdio MCP server.

Reads server registrations from:
  1. ~/.claude.json        (user scope, "mcpServers" key)
  2. ./.mcp.json           (project scope, "mcpServers" key) — overrides user

Usage:
  mcp list                          list known servers + origin
  mcp <server> tools                list tools the server exposes
  mcp <server> call <tool> [--json '{"k":"v"}'] [--arg k=v ...]
  mcp <server> resources            list resources
  mcp <server> read <uri>           read a resource
  mcp <server> prompts              list prompts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

# Tool output frequently contains Unicode (warning signs, box-drawing, emoji);
# Windows default cp1252 stdout would UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _load_servers() -> tuple[dict[str, dict], dict[str, str]]:
    """Return (merged servers, origin map). Project entries win on key collision."""
    merged: dict[str, dict] = {}
    origin: dict[str, str] = {}

    user_path = Path.home() / ".claude.json"
    if user_path.exists():
        try:
            data = json.loads(user_path.read_text(encoding="utf-8"))
            for name, cfg in (data.get("mcpServers") or {}).items():
                merged[name] = cfg
                origin[name] = "user"
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: could not read {user_path}: {e}", file=sys.stderr)

    proj_path = Path.cwd() / ".mcp.json"
    if proj_path.exists():
        try:
            data = json.loads(proj_path.read_text(encoding="utf-8"))
            for name, cfg in (data.get("mcpServers") or {}).items():
                merged[name] = cfg
                origin[name] = "project"
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: could not read {proj_path}: {e}", file=sys.stderr)

    return merged, origin


def _server_params(cfg: dict, server_name: str = ""):
    from mcp import StdioServerParameters

    command = cfg.get("command")
    if not command:
        raise SystemExit("server config missing 'command' (only stdio servers supported)")
    args = list(cfg.get("args") or [])

    # Serena's stdio server doesn't read MCP roots; needs --project <path|name>
    # to know which codebase to operate on. Inject cwd when not already set so
    # CLI users in a project dir don't have to pre-call activate_project.
    if server_name == "serena" and not any(a == "--project" for a in args):
        args = args + ["--project", str(Path.cwd())]

    env_overlay = cfg.get("env") or {}
    env = {**os.environ, **{k: str(v) for k, v in env_overlay.items()}}
    return StdioServerParameters(command=command, args=args, env=env)


def _unwrap(obj: Any) -> Any:
    """Convert MCP SDK pydantic objects into JSON-safe primitives."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if isinstance(obj, list):
        return [_unwrap(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _unwrap(v) for k, v in obj.items()}
    return obj


def _print_tool_result(result: Any) -> None:
    """Tool results have .content = list of TextContent/ImageContent/etc.

    Print TextContent.text directly (cheapest); fall back to JSON dump."""
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                print(text)
            else:
                print(json.dumps(_unwrap(item), indent=2))
        return
    print(json.dumps(_unwrap(result), indent=2))


async def _list_roots_callback(_request=None):
    """Tell servers like codegraph where the current project lives.

    Servers query the client for `roots` during initialize; without this they
    report 'CodeGraph not initialized for this project'."""
    from mcp.types import ListRootsResult, Root

    cwd_uri = Path.cwd().resolve().as_uri()
    return ListRootsResult(roots=[Root(uri=cwd_uri, name=Path.cwd().name)])


async def _with_session(cfg: dict, action, server_name: str = ""):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params(cfg, server_name)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, list_roots_callback=_list_roots_callback) as session:
            await session.initialize()
            return await action(session)


def _parse_args_pairs(pairs: list[str]) -> dict[str, Any]:
    """Parse --arg k=v repeats into a dict. Values stay strings; use --json for typed."""
    out: dict[str, Any] = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--arg expects k=v, got: {p!r}")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def cmd_list(servers: dict, origin: dict) -> int:
    if not servers:
        print("(no MCP servers configured at user or project scope)")
        return 0
    name_w = max(len(n) for n in servers)
    for name in sorted(servers):
        cfg = servers[name]
        cmd = cfg.get("command", "?")
        args = " ".join(shlex.quote(a) for a in (cfg.get("args") or []))
        print(f"{name:<{name_w}}  [{origin[name]:<7}]  {cmd} {args}".rstrip())
    return 0


async def cmd_tools(cfg: dict, server_name: str = "") -> int:
    async def action(session):
        result = await session.list_tools()
        for tool in result.tools:
            desc = (tool.description or "").splitlines()[0][:120] if tool.description else ""
            print(f"{tool.name}  {desc}")
        return 0

    return await _with_session(cfg, action, server_name)


async def cmd_call(cfg: dict, tool: str, arguments: dict, server_name: str = "") -> int:
    async def action(session):
        result = await session.call_tool(tool, arguments)
        _print_tool_result(result)
        return 1 if getattr(result, "isError", False) else 0

    return await _with_session(cfg, action, server_name)


async def cmd_resources(cfg: dict, server_name: str = "") -> int:
    async def action(session):
        result = await session.list_resources()
        for r in result.resources:
            print(f"{r.uri}  {r.name or ''}")
        return 0

    return await _with_session(cfg, action, server_name)


async def cmd_read(cfg: dict, uri: str, server_name: str = "") -> int:
    async def action(session):
        result = await session.read_resource(uri)
        _print_tool_result(result)
        return 0

    return await _with_session(cfg, action, server_name)


async def cmd_prompts(cfg: dict, server_name: str = "") -> int:
    async def action(session):
        result = await session.list_prompts()
        for p in result.prompts:
            print(f"{p.name}  {(p.description or '').splitlines()[0][:120]}")
        return 0

    return await _with_session(cfg, action, server_name)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="mcp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("server_or_cmd", nargs="?", help="server name, or 'list'")
    parser.add_argument("subcommand", nargs="?", help="tools | call | resources | read | prompts")
    parser.add_argument("tail", nargs=argparse.REMAINDER, help="remaining args")
    ns = parser.parse_args(argv)

    servers, origin = _load_servers()

    if not ns.server_or_cmd or ns.server_or_cmd == "list":
        return cmd_list(servers, origin)

    server_name = ns.server_or_cmd
    if server_name not in servers:
        print(f"unknown server: {server_name!r}. Known: {', '.join(sorted(servers)) or '(none)'}", file=sys.stderr)
        return 2
    cfg = servers[server_name]

    sub = ns.subcommand
    tail = ns.tail or []

    if sub == "tools":
        return asyncio.run(cmd_tools(cfg, server_name))
    if sub == "resources":
        return asyncio.run(cmd_resources(cfg, server_name))
    if sub == "prompts":
        return asyncio.run(cmd_prompts(cfg, server_name))
    if sub == "read":
        if not tail:
            print("usage: mcp <server> read <uri>", file=sys.stderr)
            return 2
        return asyncio.run(cmd_read(cfg, tail[0], server_name))
    if sub == "call":
        if not tail:
            print("usage: mcp <server> call <tool> [--json '{...}'] [--arg k=v ...]", file=sys.stderr)
            return 2
        tool = tail[0]
        rest = tail[1:]
        inner = argparse.ArgumentParser(prog=f"mcp {server_name} call {tool}", add_help=False)
        inner.add_argument("--json", default=None)
        inner.add_argument("--arg", action="append", default=[])
        call_ns = inner.parse_args(rest)
        arguments: dict[str, Any] = {}
        if call_ns.json:
            try:
                arguments = json.loads(call_ns.json)
            except json.JSONDecodeError as e:
                print(f"--json parse error: {e}", file=sys.stderr)
                return 2
        if call_ns.arg:
            arguments.update(_parse_args_pairs(call_ns.arg))
        return asyncio.run(cmd_call(cfg, tool, arguments, server_name))

    print(f"unknown subcommand: {sub!r}. Use: tools | call | resources | read | prompts", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
