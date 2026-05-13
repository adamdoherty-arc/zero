---
name: memory-tree
type: knowledge
triggers: [memory, vault, obsidian, episodic, recall, remember, knowledge, what zero knows]
agent: any
---

Zero's Memory Tree (openhuman-style Obsidian-compatible vault):

- All persistent knowledge writes go through
  `app.services.memory_tree.get_memory_tree()`.
- Three scopes:
  - `vault/sources/{source}/L{0,1,2}/` — per-source rolling buffer.
  - `vault/topics/{entity}/` — per-entity summaries.
  - `vault/global/{yyyymmdd}.md` — daily digest written by the
    `memory_vault_daily_digest` scheduler job at 04:00 UTC.
- Retrieval: `tree.search(query, scope=..., source=..., limit=...)`.
- The MemoryVault React page (`/memory-vault`) shows everything.
- Tier-3 episodic snapshots from `reachy_memory.save_summary()` are also
  mirrored here under `sources/episodic_{persona}/L0/`.
