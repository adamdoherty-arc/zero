"""
Memory Vault â€” hierarchical, Obsidian-compatible long-term memory.

Adopted from the openhuman convention (Source / Topic / Global trees with
Karpathy-style obsidian-wiki backing). Re-implemented for Zero so the
existing pgvector + JSON episodic memory stack can keep working alongside
a browsable Markdown vault.

Public surface:

    from app.services.memory_tree import get_memory_tree
    tree = get_memory_tree()
    await tree.write_chunk("gmail", "today's inbox digest", level=0)
    await tree.search("invoice", scope="global")
"""

from app.services.memory_tree.service import get_memory_tree, MemoryTreeService

__all__ = ["get_memory_tree", "MemoryTreeService"]
