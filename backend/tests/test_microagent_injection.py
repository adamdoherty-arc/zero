"""
Tests for microagent injection into realtime + OpenHands dispatch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path






class TestOpenHandsMicroagentInjection:
    def test_dispatch_prepends_microagent_context(self, monkeypatch, tmp_path):
        from app.services import microagents_service as mod
        from app.services import openhands_runtime_service as oh_mod

        public = tmp_path / "public"
        public.mkdir()
        (public / "deploy.md").write_text(
            "---\nname: deploy\ntype: workflow\ntriggers: [deploy, docker, rebuild]\n---\n"
            "Always run `docker compose build`.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_PUBLIC_ROOT", public)
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path / "repo")
        mod.get_microagents_service.cache_clear()  # type: ignore[attr-defined]
        monkeypatch.setattr(oh_mod, "_DATA_DIR", tmp_path / "openhands")

        svc = oh_mod.OpenHandsRuntimeService()
        svc._sdk = None  # type: ignore[attr-defined]
        task = asyncio.run(
            svc.dispatch("deploy the new version to production")
        )
        # Instruction should have microagent context prepended
        assert "deploy (workflow)" in task.instruction
        assert "docker compose build" in task.instruction
        # And the original instruction is still there after the separator
        assert "deploy the new version" in task.instruction

    def test_dispatch_without_match_passthrough(self, monkeypatch, tmp_path):
        from app.services import microagents_service as mod
        from app.services import openhands_runtime_service as oh_mod

        public = tmp_path / "public"
        public.mkdir()
        (public / "x.md").write_text(
            "---\nname: x\ntriggers: [reachy]\n---\nUse the motion lib.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_PUBLIC_ROOT", public)
        monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path / "repo")
        mod.get_microagents_service.cache_clear()  # type: ignore[attr-defined]
        monkeypatch.setattr(oh_mod, "_DATA_DIR", tmp_path / "openhands")

        svc = oh_mod.OpenHandsRuntimeService()
        svc._sdk = None  # type: ignore[attr-defined]
        task = asyncio.run(svc.dispatch("write some unrelated thing"))
        # No microagent matched → instruction is exactly what came in
        assert task.instruction == "write some unrelated thing"
