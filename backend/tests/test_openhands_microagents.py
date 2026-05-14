"""
Tests for the OpenHands runtime adapter + microagents loader.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


# ---- OpenHands runtime adapter ----

class TestOpenHandsRuntime:
    def test_unavailable_without_sdk(self, monkeypatch, tmp_path):
        from app.services import openhands_runtime_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "openhands")
        svc = mod.OpenHandsRuntimeService()
        # Force unavailable path regardless of host state
        svc._sdk = None  # type: ignore[attr-defined]
        assert svc.is_available() is False

    def test_dispatch_records_task_when_unavailable(self, monkeypatch, tmp_path):
        from app.services import openhands_runtime_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "openhands")
        svc = mod.OpenHandsRuntimeService()
        svc._sdk = None  # type: ignore[attr-defined]
        task = asyncio.run(svc.dispatch("refactor the X module"))
        assert task.id
        assert task.status == "failed"
        assert "OpenHands disabled" in (task.error or "")
        # Still listed
        assert len(svc.list_tasks()) == 1

    def test_invalid_workspace_rejected(self, monkeypatch, tmp_path):
        from app.services import openhands_runtime_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "openhands")
        svc = mod.OpenHandsRuntimeService()
        svc._sdk = None  # type: ignore[attr-defined]

        async def run():
            try:
                await svc.dispatch("x", workspace="kubernetes")
                return False
            except ValueError:
                return True

        assert asyncio.run(run()) is True

    def test_persistence_roundtrip(self, monkeypatch, tmp_path):
        from app.services import openhands_runtime_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "openhands")
        svc1 = mod.OpenHandsRuntimeService()
        svc1._sdk = None  # type: ignore[attr-defined]
        t = asyncio.run(svc1.dispatch("task A"))
        svc2 = mod.OpenHandsRuntimeService()
        assert svc2.get(t.id) is not None

    def test_cancel_unknown_raises(self, monkeypatch, tmp_path):
        from app.services import openhands_runtime_service as mod
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path / "openhands")
        svc = mod.OpenHandsRuntimeService()

        async def run():
            try:
                await svc.cancel("missing-id")
                return False
            except KeyError:
                return True

        assert asyncio.run(run()) is True


# ---- Microagents ----

class TestMicroagents:
    def test_parses_frontmatter_inline_list(self, tmp_path):
        from app.services.microagents_service import load_microagent
        p = tmp_path / "test.md"
        p.write_text(
            "---\n"
            "name: test\n"
            "type: knowledge\n"
            "triggers: [foo, bar, baz]\n"
            "---\n"
            "\nBody text here.\n",
            encoding="utf-8",
        )
        ma = load_microagent(p)
        assert ma is not None
        assert ma.name == "test"
        assert ma.type == "knowledge"
        assert ma.triggers == ["foo", "bar", "baz"]
        assert "Body text" in ma.body

    def test_parses_frontmatter_block_list(self, tmp_path):
        from app.services.microagents_service import load_microagent
        p = tmp_path / "test.md"
        p.write_text(
            "---\n"
            "name: test\n"
            "triggers:\n"
            "  - foo\n"
            "  - bar\n"
            "---\n"
            "\nBody.\n",
            encoding="utf-8",
        )
        ma = load_microagent(p)
        assert ma is not None
        assert ma.triggers == ["foo", "bar"]

    def test_match_keyword(self, tmp_path):
        from app.services.microagents_service import Microagent
        ma = Microagent(
            name="x", type="knowledge", triggers=["python", "fastapi"],
            body="body", path=tmp_path / "x.md",
        )
        assert ma.matches("How do I use Python here?") is True
        assert ma.matches("FastAPI is great") is True
        assert ma.matches("Tell me about Rust") is False

    def test_match_empty_text(self, tmp_path):
        from app.services.microagents_service import Microagent
        ma = Microagent(
            name="x", type="knowledge", triggers=["python"],
            body="body", path=tmp_path / "x.md",
        )
        assert ma.matches("") is False
        assert ma.matches(None) is False  # type: ignore[arg-type]

    def test_no_triggers_never_matches(self, tmp_path):
        from app.services.microagents_service import Microagent
        ma = Microagent(
            name="x", type="knowledge", triggers=[],
            body="body", path=tmp_path / "x.md",
        )
        assert ma.matches("python everywhere") is False

    def test_compose_returns_empty_when_no_match(self, monkeypatch, tmp_path):
        from app.services import microagents_service as mod
        monkeypatch.setattr(mod, "_PUBLIC_ROOT", tmp_path / "public")
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path / "repo")
        svc = mod.MicroagentsService()
        assert svc.compose_context_for("nothing here matches") == ""

    def test_compose_concatenates_matches(self, monkeypatch, tmp_path):
        from app.services import microagents_service as mod
        public = tmp_path / "public"
        public.mkdir()
        (public / "py.md").write_text(
            "---\nname: py\ntype: rules\ntriggers: [python]\n---\nUse async.\n",
            encoding="utf-8",
        )
        (public / "ts.md").write_text(
            "---\nname: ts\ntype: rules\ntriggers: [typescript]\n---\nNo any.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_PUBLIC_ROOT", public)
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path / "repo")
        svc = mod.MicroagentsService()
        out = svc.compose_context_for("write python and typescript")
        assert "py (rules)" in out
        assert "ts (rules)" in out
        assert "Use async" in out
        assert "No any" in out

    def test_compose_respects_max_chars(self, monkeypatch, tmp_path):
        from app.services import microagents_service as mod
        public = tmp_path / "public"
        public.mkdir()
        for i in range(5):
            (public / f"a{i}.md").write_text(
                f"---\nname: a{i}\ntriggers: [foo]\n---\n" + ("x" * 800) + "\n",
                encoding="utf-8",
            )
        monkeypatch.setattr(mod, "_PUBLIC_ROOT", public)
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path / "repo")
        svc = mod.MicroagentsService()
        out = svc.compose_context_for("foo", max_chars=1500)
        assert "trimmed" in out
        assert len(out) <= 1500 + 200  # small overshoot allowance


class TestBundledMicroagents:
    def test_public_microagents_load(self):
        """The microagents/ files we shipped should all parse."""
        from app.services.microagents_service import discover_microagents
        public_root = Path(__file__).resolve().parents[2] / "microagents"
        agents = discover_microagents([public_root])
        assert len(agents) >= 1
        names = {a.name for a in agents}
        # Confirm at least one expected agent landed
        assert any(n in names for n in {"reachy-motion", "zero-python", "memory-vault"})

    def test_repo_microagents_load(self):
        """The .openhands/microagents/ file we shipped should parse."""
        from app.services.microagents_service import discover_microagents
        repo_root = Path(__file__).resolve().parents[2] / ".openhands" / "microagents"
        agents = discover_microagents([repo_root])
        assert any(a.name == "zero-deploy" for a in agents)

    def test_reachy_motion_triggers_match(self):
        """Smoke: 'reachy' in user input must surface the reachy-motion agent."""
        from app.services.microagents_service import MicroagentsService
        svc = MicroagentsService()
        matches = svc.match("Make reachy do a happy dance")
        assert any(m.name == "reachy-motion" for m in matches)
