# Installing the cyanheads Obsidian MCP Server

One-time setup. Blocks on two Obsidian steps, then a single `.mcp.json` entry.

## 1. Install and enable the Local REST API plugin in Obsidian

1. Open Obsidian with the `C:\code\vault\ObsidianZero` vault.
2. Settings → Community plugins → Browse → search "Local REST API" → Install → Enable.
3. Settings → Local REST API → Copy the API key (you'll need it in step 3). Note the insecure HTTP port (default 27123). Enable HTTPS if you want TLS; config below uses HTTP.

## 2. Verify the plugin is live

```bash
curl -H "Authorization: Bearer <YOUR_API_KEY>" http://127.0.0.1:27123/vault/
```

Should return a JSON listing of the vault root. If it returns 401, the API key is wrong. If it hangs, Obsidian isn't running.

## 3. Add the MCP server to `.mcp.json`

Put your API key into `c:\code\zero\.env` as `OBSIDIAN_API_KEY=...`, then append this block to `c:\code\zero\.mcp.json`:

```json
"obsidian": {
  "command": "cmd",
  "args": ["/c", "npx", "-y", "@cyanheads/obsidian-mcp-server"],
  "env": {
    "OBSIDIAN_BASE_URL": "http://127.0.0.1:27123",
    "OBSIDIAN_API_KEY": "${OBSIDIAN_API_KEY}",
    "OBSIDIAN_VAULT_PATH": "C:\\code\\vault\\ObsidianZero"
  }
}
```

The package is published to npm as `@cyanheads/obsidian-mcp-server` (pin a specific version if you want: `@cyanheads/obsidian-mcp-server@0.x`).

## 4. What it unlocks

- `obsidian.append_to_section` — append-only under an H2 marker (`## Agent Summary`, `## Commits`, etc.) per the vault CLAUDE.md contract. This is how morning digest + voice turns go into daily notes without ever overwriting human-owned content.
- `obsidian.patch_frontmatter` — merge-patch frontmatter for fields in the `agent_writable` list (like `tasks_open` or `health`).
- `obsidian.create_note` — safe creation when the path doesn't exist, gated by the agent_proposals_to convention.

Zero's internal `vault_writer_service` keeps working for `00_Meta/_agent/**` writes regardless. Cyanheads is additive: it unlocks safe writes to human-owned notes.

## 5. Troubleshooting

- **MCP server fails at session start**: Obsidian isn't running or the plugin is disabled. Restart Obsidian.
- **401 Unauthorized**: The API key in `.env` doesn't match the plugin. Regenerate the key in the plugin settings.
- **Writes don't appear**: The plugin may be configured for a different vault. Confirm `OBSIDIAN_VAULT_PATH` matches the vault currently open in Obsidian.

---

## 6. Stage 1 wiring - switch `vault_writer_service` to MCP

The current `C:\code\zero\backend\app\services\vault_writer_service.py` writes filesystem-direct to `00_Meta/_agent/` only. Stage 1 unlocks safe writes outside `_agent/` by routing through cyanheads.

Replacement skeleton:

```python
# Inside vault_writer_service.py
from app.clients.cyanheads_mcp import CyanheadsMCPClient

class VaultWriterService:
    def __init__(self, mcp: CyanheadsMCPClient):
        self.mcp = mcp

    async def append_under_heading(self, path: str, heading: str, content: str, run_id: str):
        # 1. Pre-flight: read frontmatter, check agent_writable / agent_append_section
        meta = await self.mcp.get_frontmatter(path)
        if not self._heading_allowed(meta, heading):
            return await self._write_proposal(path, heading, content, run_id)

        # 2. mtime check before write (poor-man's optimistic concurrency)
        before_mtime = meta.get("_mtime")

        # 3. Append with audit footer
        footer = (
            f"\n<!-- agent-run-id: {run_id} source: zero "
            f"at: {datetime.now().isoformat()} -->\n"
        )
        return await self.mcp.append_under_heading(
            path=path,
            heading=heading,
            content=content + footer,
            mtime_check=before_mtime,
        )

    async def patch_frontmatter(self, path: str, key: str, value, run_id: str):
        meta = await self.mcp.get_frontmatter(path)
        if key not in meta.get("agent_writable", []):
            return await self._write_proposal(path, f"frontmatter:{key}", str(value), run_id)
        return await self.mcp.patch_frontmatter(path=path, key=key, value=value)
```

`_agent/` namespace continues to write filesystem-direct (faster, no MCP roundtrip, no risk of clobbering human content because nothing human is in there).

## 7. Negative tests - prove the safety contract

Stage 1 promotes only when these all pass:

```bash
# A. Allowed: append under '## Agent Summary' on a daily note (which whitelists it)
curl -X POST http://localhost:18792/api/zero/vault/append \
     -H "Content-Type: application/json" \
     -d '{"path":"20_Calendar/Daily/'$(date +%Y-%m-%d)'.md","heading":"Agent Summary","content":"_smoke test_"}'
# expect: 200, line appears under '## Agent Summary' in Obsidian within 1s

# B. Forbidden: try to write under a non-whitelisted heading
curl -X POST http://localhost:18792/api/zero/vault/append \
     -d '{"path":"30_Efforts/32_Legion/README.md","heading":"Random Heading","content":"x"}'
# expect: 200 with response "diverted_to_proposal: 00_Meta/_agent/proposals/<...>"
ls C:/code/vault/ObsidianZero/00_Meta/_agent/proposals/ | tail -3

# C. Forbidden: try to touch '.obsidian/' or '.git/'
curl -X POST http://localhost:18792/api/zero/vault/append \
     -d '{"path":".obsidian/workspace.json","heading":"x","content":"y"}'
# expect: 400 with response "blocked_path"

# D. Concurrency: write twice in flight; second write detects mtime change
# (manual: edit the file in Obsidian between the two calls)
```

## 8. Verification gate (Stage 1 -> Stage 2)

Promote only when ALL of these hold for 7 consecutive days:

- Daily-note `## Agent Summary` appended every morning by Zero with no human edits required.
- `obsidian-git` log shows `auto: agent writes` commits at ~10-15 min cadence.
- 100% of off-whitelist write attempts divert to proposals (count of `00_Meta/_agent/proposals/*.md` grows monotonically).
- Retrieval eval (30 hand-written queries from `vault_qa.json`) hits >=80% top-3 accuracy after Qwen3-Reranker-0.6B is wired into LiteLLM.

## 9. Operational notes

- cyanheads is <1 year old; expect breaking changes in 2026. Pin via `@cyanheads/obsidian-mcp-server@<commit>` once you settle on a version.
- Wrap the client behind `app/clients/cyanheads_mcp.py` so a swap-out is one file.
- If Obsidian's own CLI stabilizes (Insiders shipped early 2026), it eliminates the Local REST API plugin dependency. Revisit Q3 2026.
- HTTPS-on-localhost: even though the cert is self-signed, prefer it over HTTP - any process on the box that can curl localhost:27123 has full vault read; HTTPS narrows that to processes that explicitly accept the self-signed cert.
- Never run cyanheads with `OBSIDIAN_VERIFY_SSL=false` in any non-localhost deployment.

## References

- Strategy: `claude/docs/SecondBrain.md` section 4.
- Vault constitution: `C:\code\vault\ObsidianZero\00_Meta\CLAUDE.md`.
- Mandate: `C:\code\zero\MANDATE.md` (vault contract section).
- Active plan: `C:\Users\hadam\.claude\plans\review-the-two-lively-cascade.md` Stage 1.
- cyanheads upstream: https://github.com/cyanheads/obsidian-mcp-server
