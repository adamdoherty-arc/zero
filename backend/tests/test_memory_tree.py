"""
Tests for the Memory Vault service (chunking + vault writes + search).
"""

from __future__ import annotations

import asyncio
from pathlib import Path


class TestChunker:
    def test_empty_returns_empty(self):
        from app.services.memory_tree.chunker import chunk_text
        assert chunk_text("") == []

    def test_short_text_one_chunk(self):
        from app.services.memory_tree.chunker import chunk_text
        chunks = chunk_text("hello world")
        assert len(chunks) == 1
        assert chunks[0].text == "hello world"
        assert chunks[0].token_count >= 0

    def test_splits_on_paragraphs(self):
        from app.services.memory_tree.chunker import chunk_text
        text = "para one " * 200 + "\n\n" + "para two " * 200
        chunks = chunk_text(text, max_tokens=200)
        assert len(chunks) >= 2

    def test_hard_cut_oversized(self):
        from app.services.memory_tree.chunker import chunk_text
        text = "x" * 50000  # no spaces, single paragraph
        chunks = chunk_text(text, max_tokens=500)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c.text) <= 500 * 4


class TestVault:
    def test_slugify(self):
        from app.services.memory_tree.vault import slugify
        assert slugify("Hello World!") == "hello-world"
        assert slugify("") == "chunk"
        # Limit length
        assert len(slugify("x" * 200, max_len=20)) <= 20

    def test_write_and_read_roundtrip(self, tmp_path):
        from app.services.memory_tree.vault import write_chunk, read_entry, vault_root
        root = vault_root(tmp_path)
        path = write_chunk(
            root,
            source="gmail",
            level=0,
            title="Inbox snapshot",
            body="Three emails about taxes.",
            tags=["finance"],
        )
        assert path.exists()
        assert "L0" in str(path)
        entry = read_entry(path)
        assert entry is not None
        assert entry.frontmatter["source"] == "gmail"
        assert "Three emails" in entry.body
        raw = path.read_text(encoding="utf-8")
        assert "agent_run_id:" in raw
        assert "agent_writable: []" in raw
        assert "<!-- agent-run-id:" in raw

    def test_multi_chunk_filenames_are_unique_and_parted(self, tmp_path):
        from app.services.memory_tree.service import MemoryTreeService

        svc = MemoryTreeService(data_dir=tmp_path)
        body = ("first long paragraph about taxes. " * 450) + "\n\n" + (
            "second long paragraph about calendars. " * 450
        )

        async def run():
            paths = await svc.write_chunk("gmail", body, title="Inbox snapshot")
            assert len(paths) >= 2
            names = [p.name for p in paths]
            assert len(set(names)) == len(names)
            assert any("-p001-" in name for name in names)
            assert any("-p002-" in name for name in names)
            for path in paths:
                raw = path.read_text(encoding="utf-8")
                assert "type: memory_vault_chunk" in raw
                assert "agent_run_id:" in raw
                assert "<!-- agent-run-id:" in raw

        asyncio.run(run())

    def test_global_digest(self, tmp_path):
        from app.services.memory_tree.vault import write_global_digest, vault_root
        root = vault_root(tmp_path)
        path = write_global_digest(
            root,
            title="Daily",
            body="Today: lots happened.",
            sources=["gmail", "calendar"],
        )
        assert path.exists()
        assert "global" in str(path)

    def test_list_entries_scoped(self, tmp_path):
        from app.services.memory_tree.vault import (
            list_entries,
            vault_root,
            write_chunk,
            write_topic,
            write_global_digest,
        )
        root = vault_root(tmp_path)
        write_chunk(root, source="gmail", level=0, title="t1", body="email body")
        write_topic(root, entity="user", title="profile", body="user prefs")
        write_global_digest(root, title="day", body="digest text")
        all_entries = list_entries(root)
        assert len(all_entries) == 3
        source_entries = list_entries(root, scope="source")
        assert len(source_entries) == 1
        topic_entries = list_entries(root, scope="topic")
        assert len(topic_entries) == 1
        global_entries = list_entries(root, scope="global")
        assert len(global_entries) == 1


class TestService:
    def test_default_root_uses_canonical_vault_path(self, monkeypatch, tmp_path):
        from app.services.memory_tree import service as service_mod
        from app.services.memory_tree.service import MemoryTreeService

        class Settings:
            vault_path = str(tmp_path / "ObsidianZero")

        monkeypatch.setattr(service_mod, "_DATA_DIR", service_mod._DEFAULT_DATA_DIR)
        monkeypatch.setattr(service_mod, "get_settings", lambda: Settings())
        svc = MemoryTreeService()
        assert svc.root == (
            tmp_path / "ObsidianZero" / "00_Meta" / "_agent" / "memory_vault"
        )

    def test_write_chunk_and_search(self, tmp_path):
        from app.services.memory_tree.service import MemoryTreeService

        svc = MemoryTreeService(data_dir=tmp_path)

        async def run():
            paths = await svc.write_chunk(
                "gmail",
                "Your tax invoice from 2024 totals $1200. Pay by April.",
                level=0,
                title="Tax invoice",
            )
            assert len(paths) == 1
            hits = await svc.search("invoice")
            assert len(hits) >= 1
            assert "Tax invoice" in hits[0].title
            assert hits[0].score > 0

        asyncio.run(run())

    def test_search_scoped(self, tmp_path):
        from app.services.memory_tree.service import MemoryTreeService

        svc = MemoryTreeService(data_dir=tmp_path)

        async def run():
            await svc.write_chunk("gmail", "tax invoice arrived", title="tax-i")
            await svc.write_topic("acme", "Acme deal terms about tax season")
            await svc.write_global_digest("Daily summary mentions tax filings")
            all_hits = await svc.search("tax")
            assert len(all_hits) >= 3
            only_global = await svc.search("tax", scope="global")
            assert all(h.path.parent.name == "global" for h in only_global)
            only_source = await svc.search("tax", scope="source")
            assert all("sources" in str(h.path) for h in only_source)

        asyncio.run(run())

    def test_stats(self, tmp_path):
        from app.services.memory_tree.service import MemoryTreeService

        svc = MemoryTreeService(data_dir=tmp_path)

        async def run():
            await svc.write_chunk("gmail", "hello world", title="t1")
            await svc.write_chunk("slack", "another", title="t2")
            await svc.write_topic("acme", "acme stuff")
            stats = svc.stats()
            assert "gmail" in stats["sources"]
            assert "slack" in stats["sources"]
            assert "acme" in stats["topics"]

        asyncio.run(run())


class TestRouterSafety:
    def test_entry_blocks_path_traversal(self, monkeypatch, tmp_path):
        from fastapi import HTTPException
        from app.routers import memory_tree as router

        root = tmp_path / "vault"
        root.mkdir()

        class Tree:
            pass

        tree = Tree()
        tree.root = root
        monkeypatch.setattr(router, "get_memory_tree", lambda: tree)

        async def run():
            try:
                await router.entry("../secret.md")
                return None
            except HTTPException as exc:
                return exc

        exc = asyncio.run(run())
        assert exc is not None
        assert exc.status_code == 400

    def test_http_chunk_write_queues_approval(self, monkeypatch):
        from app.routers import memory_tree as router

        captured = {}

        async def fake_approval(**kwargs):
            captured.update(kwargs)
            return {"status": "approval_required", "approval_id": "ap-test"}

        monkeypatch.setattr(router, "queue_side_effect_approval", fake_approval)
        req = router.ChunkWriteRequest(source="gmail", body="hello", title="Inbox")
        result = asyncio.run(router.write_chunk(req))

        assert result["status"] == "approval_required"
        assert captured["tool_name"] == "memory_vault.write_chunk"
        assert captured["tier"] == "write_local"
        assert captured["arguments"]["source"] == "gmail"
