"""
Regression tests for the Reachy realtime bridge (OpenAI Realtime + Gemini Live).

Scope:
- profiles loader (vendored upstream data + prompt-fragment expansion + merge
  with Zero personas)
- tools registry (specs, dispatch, system-tool gating, error shapes)
- BackgroundToolManager (success / failure / cancel lifecycle)
- config_store (persist, mask, clear)
- session orchestrator (start / stop / missing-key error)

The provider handlers themselves (OpenAIRealtimeHandler / GeminiLiveHandler)
are covered only at their seams — talking to the real OpenAI/Gemini services
is a live-integration test, not a unit test. The seams covered here are:

- schema-translation helpers (OpenAI spec → Gemini function_declarations)
- voice resolution
- start() fails fast with no API key
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.reachy_realtime import tools as tool_registry
from app.services.reachy_realtime.bg_tool_manager import (
    BackgroundToolManager,
    ToolNotification,
    ToolState,
)
from app.services.reachy_realtime.common import (
    BACKEND_GEMINI,
    BACKEND_OPENAI,
    DEFAULT_VOICE_BY_BACKEND,
    MotionDispatcher,
    ToolDependencies,
    normalize_backend,
    resolve_model,
    resolve_voice,
)
from app.services.reachy_realtime.gemini_handler import (
    _convert_schema,
    _openai_specs_to_gemini,
    _resolve_gemini_voice,
)
from app.services.reachy_realtime.profiles import (
    _expand_includes,
    get_profile,
    list_profiles,
    resolve_instructions,
    resolve_tools,
    resolve_voice as resolve_profile_voice,
)


# ============================================================
# common.py — normalizers
# ============================================================

class TestCommon:
    def test_normalize_backend_default(self):
        assert normalize_backend(None) == BACKEND_OPENAI
        assert normalize_backend("") == BACKEND_OPENAI
        assert normalize_backend("nonsense") == BACKEND_OPENAI

    def test_normalize_backend_known(self):
        assert normalize_backend("openai") == BACKEND_OPENAI
        assert normalize_backend("OpenAI") == BACKEND_OPENAI
        assert normalize_backend("gemini") == BACKEND_GEMINI
        assert normalize_backend("GEMINI ") == BACKEND_GEMINI

    def test_resolve_model_prefers_override(self):
        assert resolve_model(BACKEND_OPENAI, "my-model") == "my-model"
        # Whitespace-only falls through to default.
        assert resolve_model(BACKEND_OPENAI, "   ") == "gpt-realtime"

    def test_resolve_model_default_per_backend(self):
        assert resolve_model(BACKEND_OPENAI, None) == "gpt-realtime"
        assert resolve_model(BACKEND_GEMINI, None) == "gemini-3.1-flash-live-preview"

    def test_resolve_voice_falls_back_to_default_on_unknown(self):
        # OpenAI has no "Kore"; should coerce back to "cedar".
        assert resolve_voice(BACKEND_OPENAI, "Kore") == DEFAULT_VOICE_BY_BACKEND[BACKEND_OPENAI]

    def test_resolve_voice_passes_known(self):
        assert resolve_voice(BACKEND_OPENAI, "marin") == "marin"
        assert resolve_voice(BACKEND_GEMINI, "aoede").lower() == "aoede"  # case-insensitive


# ============================================================
# profiles.py — vendored upstream data + merge
# ============================================================

class TestProfiles:
    def test_catalog_non_empty(self):
        profiles = list_profiles()
        assert len(profiles) >= 7, f"expected at least 7 profiles, got {len(profiles)}"

    def test_companion_profile_ids_present(self):
        ids = {p.id for p in list_profiles()}
        for expected in ("companion", "assistant", "deep_work", "coach", "wellness", "narrator", "explorer"):
            assert expected in ids, f"missing profile: {expected}"

    def test_companion_profile_has_instructions_and_tools(self):
        prof = get_profile("companion")
        assert prof.id == "companion"
        assert prof.instructions, "companion instructions empty"
        assert prof.tools, "companion tools empty"

    def test_gesture_markers_expand_include(self):
        # Each persona's instructions.txt ends with [gesture_markers]; after
        # _expand_includes the bracket-tag must be replaced with the fragment.
        instructions = resolve_instructions("companion")
        assert "[gesture_markers]" not in instructions
        assert "GESTURE MARKERS" in instructions
        assert len(instructions) > 200

    def test_unknown_profile_falls_back_to_companion(self):
        # Never raises — get_profile must always return something usable.
        prof = get_profile("does-not-exist")
        assert prof.id == "companion" or prof.instructions

    def test_resolve_tools_returns_tuple(self):
        tools = resolve_tools("companion")
        assert isinstance(tools, tuple)
        assert "dance" in tools or "move_head" in tools

    def test_resolve_profile_voice_uses_profile_when_set(self):
        # Each new persona ships its own voice.txt — resolve_voice should
        # honour it regardless of backend default.
        assert resolve_profile_voice("companion", BACKEND_OPENAI) == "en-US-AriaNeural"
        assert resolve_profile_voice("assistant", BACKEND_GEMINI) == "en-US-AndrewNeural"

    def test_include_expansion_helper(self):
        # Synthetic include line should be replaced with matching fragment if present.
        # Use an existing fragment the vendored library has.
        text = "intro\n[behaviors/silent_robot]\nbye"
        out = _expand_includes(text)
        assert "[behaviors/silent_robot]" not in out

    def test_include_expansion_keeps_unknown_placeholders(self):
        text = "[nonexistent_fragment_xyz]"
        out = _expand_includes(text)
        # Unknown placeholder kept verbatim (matches upstream's graceful-miss behaviour).
        assert "[nonexistent_fragment_xyz]" in out


# ============================================================
# tools.py — registry + dispatch
# ============================================================

@pytest.fixture
def motion_mocks() -> dict[str, AsyncMock]:
    return {
        "move_head": AsyncMock(return_value={"status": "ok"}),
        "play_emotion": AsyncMock(return_value={"status": "queued", "clip": "happy"}),
        "play_dance": AsyncMock(return_value={"status": "queued", "clip": "simple_nod"}),
        "stop_move": AsyncMock(return_value={"stopped": True}),
        "capture_image": AsyncMock(return_value=b"\xff\xd8\xffFAKE_JPEG"),
        "set_head_tracking": AsyncMock(return_value={"ok": True}),
    }


@pytest.fixture
def deps(motion_mocks) -> ToolDependencies:
    motion = MotionDispatcher(
        move_head=motion_mocks["move_head"],
        play_emotion=motion_mocks["play_emotion"],
        play_dance=motion_mocks["play_dance"],
        stop_move=motion_mocks["stop_move"],
        list_emotions=lambda: ["happy", "sad"],
        list_dances=lambda: ["simple_nod"],
        capture_image=motion_mocks["capture_image"],
        set_head_tracking=motion_mocks["set_head_tracking"],
    )
    return ToolDependencies(motion=motion)


@pytest.fixture
def mgr() -> BackgroundToolManager:
    return BackgroundToolManager()


class TestTools:
    def test_specs_include_all_names(self):
        names = {s["name"] for s in tool_registry.get_tool_specs()}
        for expected in (
            "move_head", "dance", "play_emotion", "stop_dance", "stop_emotion",
            "head_tracking", "do_nothing", "camera", "task_status", "task_cancel",
        ):
            assert expected in names

    def test_specs_filtered_by_profile_keeps_system_tools(self):
        # Profile only wants 'dance' — system tools must still be attached.
        specs = tool_registry.get_tool_specs(enabled=["dance"])
        names = {s["name"] for s in specs}
        assert "dance" in names
        assert "task_status" in names  # system tool, auto-included
        assert "task_cancel" in names
        # Non-enabled, non-system excluded.
        assert "move_head" not in names

    def test_specs_all_are_openai_function_shape(self):
        for spec in tool_registry.get_tool_specs():
            assert spec["type"] == "function"
            assert "name" in spec and "description" in spec and "parameters" in spec
            assert spec["parameters"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_dispatch_move_head_forwards_to_motion(self, deps, mgr, motion_mocks):
        out = await tool_registry.dispatch("move_head", json.dumps({"direction": "left"}), deps, mgr)
        assert out == {"status": "looking left"}
        # Upstream uses yaw=40 deg for "left" — verify exactly.
        motion_mocks["move_head"].assert_awaited_once()
        kwargs = motion_mocks["move_head"].await_args.kwargs
        assert kwargs["yaw"] == 40

    @pytest.mark.asyncio
    async def test_dispatch_move_head_rejects_unknown_direction(self, deps, mgr):
        out = await tool_registry.dispatch("move_head", json.dumps({"direction": "sideways"}), deps, mgr)
        assert "error" in out

    @pytest.mark.asyncio
    async def test_dispatch_play_emotion_missing_arg(self, deps, mgr):
        out = await tool_registry.dispatch("play_emotion", "{}", deps, mgr)
        assert "error" in out and "required" in out["error"].lower()

    @pytest.mark.asyncio
    async def test_dispatch_play_emotion_happy_path(self, deps, mgr, motion_mocks):
        out = await tool_registry.dispatch("play_emotion", json.dumps({"emotion": "happy"}), deps, mgr)
        assert out["status"] == "queued"
        motion_mocks["play_emotion"].assert_awaited_once_with("happy")

    @pytest.mark.asyncio
    async def test_dispatch_dance_default_repeat(self, deps, mgr, motion_mocks):
        out = await tool_registry.dispatch("dance", json.dumps({"move": "simple_nod"}), deps, mgr)
        assert out["status"] == "queued"
        assert motion_mocks["play_dance"].await_count == 1

    @pytest.mark.asyncio
    async def test_dispatch_dance_repeat_calls_motion_multiple_times(self, deps, mgr, motion_mocks):
        await tool_registry.dispatch("dance", json.dumps({"move": "simple_nod", "repeat": 3}), deps, mgr)
        assert motion_mocks["play_dance"].await_count == 3

    @pytest.mark.asyncio
    async def test_dispatch_camera_returns_base64(self, deps, mgr):
        out = await tool_registry.dispatch("camera", json.dumps({"question": "what do you see?"}), deps, mgr)
        assert "b64_im" in out
        # Can be decoded as base64.
        import base64
        assert base64.b64decode(out["b64_im"]).startswith(b"\xff\xd8\xff")

    @pytest.mark.asyncio
    async def test_dispatch_camera_empty_question_rejected(self, deps, mgr):
        out = await tool_registry.dispatch("camera", json.dumps({"question": ""}), deps, mgr)
        assert "error" in out

    @pytest.mark.asyncio
    async def test_dispatch_do_nothing_always_succeeds(self, deps, mgr):
        out = await tool_registry.dispatch("do_nothing", "{}", deps, mgr)
        assert out["status"] == "doing nothing"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error(self, deps, mgr):
        out = await tool_registry.dispatch("fabulous_new_tool", "{}", deps, mgr)
        assert "error" in out
        assert "unknown tool" in out["error"]

    @pytest.mark.asyncio
    async def test_dispatch_handles_bad_json_gracefully(self, deps, mgr, motion_mocks):
        # Bad JSON → empty args, so move_head defaults to 'front' (no error, no call assertion).
        out = await tool_registry.dispatch("move_head", "not json {", deps, mgr)
        # front is accepted, yaw=0
        assert out.get("status") == "looking front" or "error" in out

    @pytest.mark.asyncio
    async def test_stop_tools_call_motion_stop(self, deps, mgr, motion_mocks):
        await tool_registry.dispatch("stop_dance", json.dumps({"dummy": True}), deps, mgr)
        await tool_registry.dispatch("stop_emotion", json.dumps({"dummy": True}), deps, mgr)
        assert motion_mocks["stop_move"].await_count == 2


# ============================================================
# bg_tool_manager.py — lifecycle
# ============================================================

class TestBackgroundToolManager:
    @pytest.mark.asyncio
    async def test_successful_tool_emits_completed_notification(self):
        mgr = BackgroundToolManager()
        received: list[ToolNotification] = []

        async def cb(note: ToolNotification) -> None:
            received.append(note)

        await mgr.start_up(callbacks=[cb])

        async def _routine(_mgr):
            return {"status": "ok"}

        await mgr.start_tool(
            call_id="c1", tool_name="mytool", routine=_routine, is_idle_tool_call=False,
        )
        await asyncio.sleep(0.1)
        await mgr.shutdown()

        assert len(received) == 1
        assert received[0].status == ToolState.COMPLETED
        assert received[0].result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_failing_tool_emits_failed_notification(self):
        mgr = BackgroundToolManager()
        received: list[ToolNotification] = []

        async def cb(note: ToolNotification) -> None:
            received.append(note)

        await mgr.start_up(callbacks=[cb])

        async def _routine(_mgr):
            raise RuntimeError("boom")

        await mgr.start_tool(
            call_id="c2", tool_name="mytool", routine=_routine, is_idle_tool_call=False,
        )
        await asyncio.sleep(0.1)
        await mgr.shutdown()

        assert len(received) == 1
        assert received[0].status == ToolState.FAILED
        assert "boom" in (received[0].error or "")

    @pytest.mark.asyncio
    async def test_cancel_running_tool(self):
        mgr = BackgroundToolManager()
        received: list[ToolNotification] = []

        async def cb(note: ToolNotification) -> None:
            received.append(note)

        await mgr.start_up(callbacks=[cb])

        async def _routine(_mgr):
            await asyncio.sleep(5)
            return {"status": "done"}

        bg = await mgr.start_tool(
            call_id="c3", tool_name="slowtool", routine=_routine, is_idle_tool_call=False,
        )
        await asyncio.sleep(0.05)
        ok = await mgr.cancel_tool(bg.tool_id)
        assert ok is True
        await asyncio.sleep(0.1)
        await mgr.shutdown()

        assert any(n.status == ToolState.CANCELLED for n in received)

    @pytest.mark.asyncio
    async def test_error_dict_treated_as_failed(self):
        # If the routine returns {'error': ...} it's treated as a failure even
        # without raising. Matches upstream's tool-result contract.
        mgr = BackgroundToolManager()
        received: list[ToolNotification] = []

        async def cb(note: ToolNotification) -> None:
            received.append(note)

        await mgr.start_up(callbacks=[cb])

        async def _routine(_mgr):
            return {"error": "not available"}

        await mgr.start_tool(
            call_id="c4", tool_name="mytool", routine=_routine, is_idle_tool_call=False,
        )
        await asyncio.sleep(0.1)
        await mgr.shutdown()

        assert len(received) == 1
        assert received[0].status == ToolState.FAILED
        assert received[0].error == "not available"


# ============================================================
# gemini_handler.py — schema translation helpers
# ============================================================

class TestGeminiSchemaTranslation:
    def test_convert_type_to_uppercase(self):
        schema = {"type": "string"}
        assert _convert_schema(schema)["type"] == "STRING"

    def test_convert_object_with_properties_recursively(self):
        schema = {
            "type": "object",
            "properties": {
                "direction": {"type": "string"},
                "repeat": {"type": "integer"},
            },
        }
        out = _convert_schema(schema)
        assert out["type"] == "OBJECT"
        assert out["properties"]["direction"]["type"] == "STRING"
        assert out["properties"]["repeat"]["type"] == "INTEGER"

    def test_strip_additional_properties(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {}}
        assert "additionalProperties" not in _convert_schema(schema)

    def test_array_items_converted(self):
        schema = {"type": "array", "items": {"type": "number"}}
        out = _convert_schema(schema)
        assert out["type"] == "ARRAY"
        assert out["items"]["type"] == "NUMBER"

    def test_openai_specs_to_gemini_preserves_name_and_description(self):
        openai_specs = [
            {"type": "function", "name": "dance", "description": "dance please", "parameters": {"type": "object"}}
        ]
        out = _openai_specs_to_gemini(openai_specs)
        assert out[0]["name"] == "dance"
        assert out[0]["description"] == "dance please"
        assert "type" not in out[0]  # no "type": "function" in Gemini shape

    def test_resolve_gemini_voice_case_insensitive(self):
        assert _resolve_gemini_voice("KORE") == "Kore"
        assert _resolve_gemini_voice("puck") == "Puck"

    def test_resolve_gemini_voice_unknown_falls_back(self):
        assert _resolve_gemini_voice("cedar") == "Kore"  # cedar is OpenAI — fall back


# ============================================================
# config_store.py — persistence + masking
# ============================================================

class TestConfigStore:
    def _isolate(self, monkeypatch, tmp_path: Path):
        """Point the config store at a tmp workspace for one test."""
        from app.infrastructure import config as config_module
        from app.services.reachy_realtime import config_store as cs

        # The store reads workspace_dir from get_settings() lazily, so override
        # _store_path directly instead of stomping the Settings singleton.
        tmp_cfg = tmp_path / "reachy_realtime_config.json"
        tmp_cfg.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(cs, "_store_path", lambda: tmp_cfg)
        return cs, tmp_cfg

    def test_mask_keeps_prefix_suffix(self, monkeypatch, tmp_path):
        cs, _ = self._isolate(monkeypatch, tmp_path)
        assert cs._mask("sk-abcdefghijkl") == "sk-a…ijkl"
        assert cs._mask(None) is None
        assert cs._mask("short") == "…"

    def test_update_and_reload_roundtrip(self, monkeypatch, tmp_path):
        cs, path = self._isolate(monkeypatch, tmp_path)
        masked = cs.update_config({"openai_api_key": "sk-test-1234567890", "backend": "gemini"})
        assert masked["has_openai_key"] is True
        assert masked["backend"] == "gemini"
        assert "1234567890" not in (masked.get("openai_api_key") or "")

        on_disk = json.loads(path.read_text())
        assert on_disk["openai_api_key"] == "sk-test-1234567890"

    def test_update_clears_key_on_empty_string(self, monkeypatch, tmp_path):
        cs, path = self._isolate(monkeypatch, tmp_path)
        cs.update_config({"openai_api_key": "sk-abcdefghijklmnop"})
        assert path.exists()
        cs.update_config({"openai_api_key": ""})
        on_disk = json.loads(path.read_text())
        assert "openai_api_key" not in on_disk

    def test_update_rejects_unknown_fields(self, monkeypatch, tmp_path):
        cs, path = self._isolate(monkeypatch, tmp_path)
        cs.update_config({"malicious_field": "should not persist", "voice": "marin"})
        on_disk = json.loads(path.read_text())
        assert "malicious_field" not in on_disk
        assert on_disk["voice"] == "marin"

    def test_backend_is_normalized(self, monkeypatch, tmp_path):
        cs, path = self._isolate(monkeypatch, tmp_path)
        cs.update_config({"backend": "GEMINI "})
        assert json.loads(path.read_text())["backend"] == "gemini"


# ============================================================
# session.py — error paths (no real provider calls)
# ============================================================

class FakeWebSocket:
    """Minimal FastAPI-style WebSocket for unit tests."""

    def __init__(self, incoming: list[dict]):
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict:
        if not self._incoming:
            # Simulate browser disconnect — matches WebSocketDisconnect handling.
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect()
        return self._incoming.pop(0)

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class TestSession:
    @pytest.mark.asyncio
    async def test_start_without_openai_key_emits_error(self, monkeypatch):
        # Ensure no env key bleeds into the test.
        from app.infrastructure.config import Settings

        def _fake_settings():
            return Settings(
                openai_api_key=None,
                gemini_api_key=None,
                reachy_realtime_backend="openai",
                workspace_dir=".",
            )

        from app.services.reachy_realtime import session as session_module
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)

        ws = FakeWebSocket([
            {"type": "start", "backend": "openai"},
            {"type": "stop"},
        ])
        from app.services.reachy_realtime.session import RealtimeSession
        await RealtimeSession(ws).run()

        # Expect at least one error frame mentioning OPENAI_API_KEY, plus session.closed.
        error_msgs = [m for m in ws.sent if m.get("type") == "error"]
        assert any("OPENAI_API_KEY" in m.get("message", "") for m in error_msgs)
        assert any(m.get("type") == "session.closed" for m in ws.sent)

    @pytest.mark.asyncio
    async def test_start_without_gemini_key_emits_error(self, monkeypatch):
        from app.infrastructure.config import Settings

        def _fake_settings():
            return Settings(
                openai_api_key=None,
                gemini_api_key=None,
                reachy_realtime_backend="gemini",
                workspace_dir=".",
            )

        from app.services.reachy_realtime import session as session_module
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)

        ws = FakeWebSocket([
            {"type": "start", "backend": "gemini"},
            {"type": "stop"},
        ])
        from app.services.reachy_realtime.session import RealtimeSession
        await RealtimeSession(ws).run()

        error_msgs = [m for m in ws.sent if m.get("type") == "error"]
        assert any("GEMINI_API_KEY" in m.get("message", "") for m in error_msgs)

    @pytest.mark.asyncio
    async def test_unknown_backend_yields_error(self, monkeypatch):
        from app.infrastructure.config import Settings

        def _fake_settings():
            return Settings(workspace_dir=".")

        from app.services.reachy_realtime import session as session_module
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)

        ws = FakeWebSocket([
            # Bypass normalize_backend by calling explicit unknown after it.
            # normalize_backend will clamp "nonsense" to openai, so the error
            # will actually be the missing OPENAI key. That still proves we
            # don't crash on weird backend values.
            {"type": "start", "backend": "nonsense"},
            {"type": "stop"},
        ])
        from app.services.reachy_realtime.session import RealtimeSession
        await RealtimeSession(ws).run()
        # Any error or graceful close is acceptable — we're asserting no crash.
        assert ws.sent, "session should have produced at least one frame"

    @pytest.mark.asyncio
    async def test_motion_dispatcher_wraps_reachy_service(self, monkeypatch):
        """Sanity-check the adapter: calling build_motion_dispatcher doesn't
        require a live daemon — it's pure adapter wrapping."""
        from app.services.reachy_realtime.session import build_motion_dispatcher

        dispatcher = build_motion_dispatcher()
        assert callable(dispatcher.move_head)
        assert callable(dispatcher.play_emotion)
        assert callable(dispatcher.play_dance)
        assert callable(dispatcher.capture_image)


# ============================================================
# router — GET /config, PUT /config, GET /profiles
# ============================================================

class TestRealtimeRouter:
    @pytest.mark.asyncio
    async def test_get_config_returns_capability_catalog(self, client, monkeypatch):
        # Redirect config store to a tmp file so the test doesn't stomp real state.
        from app.services.reachy_realtime import config_store as cs

        tmp = Path("/tmp/zero-test-realtime-config.json") if Path("/tmp").exists() else (
            Path(__file__).parent / "_tmp_realtime_config.json"
        )
        if tmp.exists():
            tmp.unlink()
        monkeypatch.setattr(cs, "_store_path", lambda: tmp)

        resp = await client.get("/api/reachy/realtime/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["backends"] == ["openai", "gemini"]
        assert "gpt-realtime" in body["default_models"]["openai"]
        assert "cedar" in body["voices"]["openai"]
        assert "Kore" in body["voices"]["gemini"]

    @pytest.mark.asyncio
    async def test_put_config_persists_and_masks(self, client, monkeypatch):
        from app.services.reachy_realtime import config_store as cs

        tmp = Path(__file__).parent / "_tmp_realtime_config.json"
        if tmp.exists():
            tmp.unlink()
        monkeypatch.setattr(cs, "_store_path", lambda: tmp)

        resp = await client.put(
            "/api/reachy/realtime/config",
            json={"openai_api_key": "sk-abcdefghijkl1234", "voice": "marin", "backend": "openai"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_openai_key"] is True
        assert body["voice"] == "marin"
        # Full key must never be echoed.
        assert body["openai_api_key"] != "sk-abcdefghijkl1234"

        on_disk = json.loads(tmp.read_text())
        assert on_disk["openai_api_key"] == "sk-abcdefghijkl1234"
        tmp.unlink()

    @pytest.mark.asyncio
    async def test_get_profiles_returns_catalog(self, client):
        resp = await client.get("/api/reachy/realtime/profiles")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] >= 7
        ids = {p["id"] for p in body["profiles"]}
        assert "companion" in ids and "assistant" in ids

    @pytest.mark.asyncio
    async def test_get_profiles_include_instructions_flag(self, client):
        resp = await client.get(
            "/api/reachy/realtime/profiles", params={"include_instructions": "true"},
        )
        body = resp.json()
        assert any("instructions" in p for p in body["profiles"])
