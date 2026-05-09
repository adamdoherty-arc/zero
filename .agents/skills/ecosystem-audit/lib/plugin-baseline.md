# Obsidian plugin baseline

Required community plugins for `c:\code\vault\ObsidianZero`, derived from
[docs/SecondBrain.md](../../../../docs/SecondBrain.md) "plugin starter set".

The audit reads `c:\code\vault\ObsidianZero\.obsidian\community-plugins.json`
and diffs against this list. Missing plugins â†’ proposal in
`00_Meta\_agent\proposals\plugin-<name>.md`. Never auto-installs.

## Tier 1 â€” non-negotiable

| Plugin id | Why | Source |
|---|---|---|
| `obsidian-git` | Auto-commit every 10â€“15 min. Without this, agent edits can clobber human edits and there is no recovery. | SecondBrain.md |
| `templater-obsidian` | Daily-note template, project-note template, agent-write template with frontmatter scaffolding. | SecondBrain.md |
| `quickadd` | Inbox capture flows that Zero invokes via Advanced URI. | SecondBrain.md |
| `obsidian-tasks-plugin` | Task syntax (`- [ ]`) with due dates, recurrence, query-able by Dataview. | SecondBrain.md |
| `periodic-notes` | Daily / weekly / monthly / quarterly notes with deterministic paths. | SecondBrain.md |
| `calendar` | Visual entrypoint to daily notes. | SecondBrain.md |
| `obsidian-advanced-uri` | Lets Zero, Legion, Ada open vault URIs from outside Obsidian. | SecondBrain.md |

## Tier 2 â€” strongly recommended

| Plugin id | Why |
|---|---|
| `dataview` | Inline queries until Bases is fully adopted. |
| `bases` | GA in Obsidian 1.9. Materialized views on YAML frontmatter; LLMs can author. |
| `obsidian-linter` | Frontmatter normalization, prevents agent + human edits drifting on whitespace. |

## Tier 3 â€” context-dependent

These are NOT required but worth checking once a quarter:

| Plugin id | Why |
|---|---|
| `dataloom` | Spreadsheet-like views for trading logs. |
| `excalidraw-obsidian` | Diagram authoring; opt-in. |
| `omnisearch` | Full-text fallback when Bases query is too narrow. |

## Hard limits

- **Cap at ~20 community plugins.** Per SecondBrain.md, remove one every
  3 months to keep the vault performant. The audit warns at 18, errors at 21.
- **Avoid Datacore for now** â€” wait 6 months past its 1.0. Audit warns if
  installed.

