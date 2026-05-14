---
name: memory-vault
type: knowledge
triggers: [memory, vault, obsidian, episodic, recall, remember, knowledge, what zero knows]
agent: any
---

Zero's Memory Vault is the Obsidian-compatible persistence layer for the
personal assistant and second brain:

- Persistent knowledge writes go through
  `app.services.memory_tree.get_memory_tree()` or the approved Memory Vault API.
- The production root is the canonical Obsidian mount:
  `/vault/00_Meta/_agent/memory_vault/`.
- Three scopes:
  - `sources/{source}/L{0,1,2}/` - per-source rolling buffer.
  - `topics/{entity}/` - per-entity summaries.
  - `global/` - daily/global digest material.
- Retrieval: `tree.search(query, scope=..., source=..., limit=...)`.
- The Memory Vault React page (`/memory-vault`) shows everything.
- HTTP writes to `/api/memory-vault/*` must create approval requests instead of
  writing directly; internal writers add audit metadata and unique filenames.
