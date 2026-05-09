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
import time
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
    BACKEND_LOCAL,
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
from app.services.reachy_head_tracking_service import ReachyHeadTrackingService


# ============================================================
# common.py — normalizers
# ============================================================

class TestCommon:
    def test_normalize_backend_default(self):
        assert normalize_backend(None) == BACKEND_LOCAL
        assert normalize_backend("") == BACKEND_LOCAL
        assert normalize_backend("nonsense") == BACKEND_LOCAL

    def test_normalize_backend_known(self):
        assert normalize_backend("openai") == BACKEND_OPENAI
        assert normalize_backend("OpenAI") == BACKEND_OPENAI
        assert normalize_backend("gemini") == BACKEND_GEMINI
        assert normalize_backend("GEMINI ") == BACKEND_GEMINI

    def test_resolve_model_prefers_override(self):
        assert resolve_model(BACKEND_OPENAI, "gpt-4o-realtime-preview") == "gpt-4o-realtime-preview"
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

    def test_resolve_voice_rejects_unavailable_local_legacy_voice(self):
        assert resolve_voice(BACKEND_LOCAL, "en_US-amy-medium") == "en-US-JennyNeural"


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
        # _expand_includes the bracket-tag must be replaced with the fragment,
        # then realtime prompts must remove marker instructions because
        # OpenAI/Gemini synthesize their own audio and would speak tags aloud.
        instructions = resolve_instructions("companion")
        assert "[gesture_markers]" not in instructions
        assert "GESTURE MARKERS" not in instructions
        assert "[emotion:" not in instructions
        assert "[dance:" not in instructions
        assert "Speak only in English" in instructions

    def test_companion_prompt_has_controlled_affection_rules(self):
        instructions = resolve_instructions("companion")
        assert "Pet names are rare" in instructions
        assert "no catchphrases" in instructions
        assert "darling" in instructions
        assert "does not block explicit user-commanded robot actions" in instructions
        assert "Do not ask to enable body motion for a direct movement command" in instructions
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
        "set_head_tracking": AsyncMock(return_value={"running": True, "state": "scanning", "detail": "No face detected yet."}),
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
    def test_resolve_model_rejects_cross_backend_values(self):
        from app.services.reachy_realtime.common import (
            BACKEND_LOCAL,
            BACKEND_OPENAI,
            resolve_model,
        )

        assert resolve_model(BACKEND_OPENAI, "qwen3-chat") == "gpt-realtime"
        assert resolve_model(BACKEND_LOCAL, "gpt-realtime") == "qwen3-chat"

    def test_specs_include_all_names(self):
        names = {s["name"] for s in tool_registry.get_tool_specs()}
        for expected in (
            "move_head", "dance", "play_emotion", "stop_dance", "stop_emotion",
            "head_tracking", "do_nothing", "camera", "task_status", "task_cancel",
        ):
            assert expected in names

    @pytest.mark.asyncio
    async def test_companion_motion_governor_blocks_whistle_clip(self, deps, mgr):
        guarded = ToolDependencies(
            motion=deps.motion,
            extra={"profile_id": "companion"},
        )
        result = await tool_registry.dispatch(
            "play_emotion",
            json.dumps({"emotion": "cheerful1"}),
            guarded,
            mgr,
        )
        assert "error" in result
        assert "disabled" in result["error"]

    @pytest.mark.asyncio
    async def test_camera_empty_frame_reports_truthful_condition(self, deps, mgr, monkeypatch):
        class FakeReachyService:
            async def get_camera_specs(self):
                return {"width": 1280, "height": 720, "fps": 15}

        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "active": False,
                    "frame_available": False,
                    "last_error": "[Errno 22] Invalid argument",
                }

        class FakeAsyncClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url):
                return FakeResponse()

        monkeypatch.setattr(
            "app.services.reachy_service.get_reachy_service",
            lambda: FakeReachyService(),
        )
        monkeypatch.setattr(tool_registry.httpx, "AsyncClient", FakeAsyncClient)
        deps.motion.capture_image = AsyncMock(return_value=b"")

        result = await tool_registry.dispatch(
            "camera",
            json.dumps({"question": "what do you see?"}),
            deps,
            mgr,
        )

        assert result["error"] == "camera frame unavailable"
        assert result["condition"] == "specs_detected_frame_worker_inactive"
        assert "Invalid argument" in result["detail"]

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
    async def test_dispatch_head_tracking_surfaces_scanning_state(self, deps, mgr, motion_mocks):
        deps.extra["latest_user_text"] = "follow my face"
        out = await tool_registry.dispatch("head_tracking", json.dumps({"start": True}), deps, mgr)

        assert out["status"] == "head tracking scanning"
        assert "No face detected" in out["detail"]
        motion_mocks["set_head_tracking"].assert_awaited_once_with(True)

    @pytest.mark.asyncio
    async def test_dispatch_head_tracking_requires_motion_opt_in_when_not_explicit(self, deps, mgr, motion_mocks):
        out = await tool_registry.dispatch("head_tracking", json.dumps({"start": True}), deps, mgr)

        assert out["error"] == "body_motion_session_off"
        motion_mocks["set_head_tracking"].assert_not_awaited()

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
    async def test_dispatch_allows_explicit_motion_when_session_body_motion_is_off(self, deps, mgr, motion_mocks):
        deps.extra["body_motion_enabled"] = False
        out = await tool_registry.dispatch("dance", json.dumps({"move": "simple_nod"}), deps, mgr)
        assert out["status"] == "queued"
        motion_mocks["play_dance"].assert_awaited_once_with("simple_nod")

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

class TestOpenAIRealtimeHandler:
    @pytest.mark.asyncio
    async def test_session_update_uses_current_realtime_token_limit_field(self):
        from app.services.reachy_realtime.openai_handler import OpenAIRealtimeHandler

        class FakeOpenAIWebSocket:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send(self, payload: str) -> None:
                self.sent.append(payload)

        fake_ws = FakeOpenAIWebSocket()
        handler = OpenAIRealtimeHandler(
            api_key="sk-test",
            model="gpt-realtime",
            voice="cedar",
            profile_id="assistant",
            deps=ToolDependencies(MotionDispatcher()),
        )
        handler._ws = fake_ws

        await handler._send_session_update()

        payload = json.loads(fake_ws.sent[0])
        session = payload["session"]
        assert session["max_output_tokens"] == 80
        assert "max_response_output_tokens" not in session
        assert session["audio"]["input"]["noise_reduction"] == {"type": "far_field"}
        assert session["audio"]["input"]["turn_detection"]["create_response"] is True
        assert session["audio"]["input"]["turn_detection"]["interrupt_response"] is True


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
        assert json.loads(path.read_text())["backend_user_selected"] is True

    def test_legacy_local_config_auto_selects_openai_when_key_exists(self, monkeypatch, tmp_path):
        cs, path = self._isolate(monkeypatch, tmp_path)
        path.write_text(json.dumps({
            "backend": "local",
            "openai_api_key": "sk-test-1234567890",
            "model": "qwen3-chat",
            "voice": "en-US-AriaNeural",
        }))

        cfg = cs.load_config_masked()

        assert cfg["backend"] == "openai"
        assert cfg["backend_source"] == "auto_openai_key"
        assert cfg["backend_user_selected"] is False
        assert cfg["model"] == "gpt-realtime"
        assert cfg["voice"] == DEFAULT_VOICE_BY_BACKEND[BACKEND_OPENAI]
        on_disk = json.loads(path.read_text())
        assert on_disk["backend"] == "openai"
        assert on_disk["backend_auto_selected"] is True
        assert "model" not in on_disk

    def test_explicit_local_backend_stays_local_even_with_openai_key(self, monkeypatch, tmp_path):
        cs, _path = self._isolate(monkeypatch, tmp_path)

        cfg = cs.update_config({
            "openai_api_key": "sk-test-1234567890",
            "backend": "local",
        })

        assert cfg["backend"] == "local"
        assert cfg["backend_source"] == "stored"
        assert cfg["backend_user_selected"] is True


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
    def test_assistant_audio_temporarily_suppresses_host_mic_echo(self):
        from app.services.reachy_realtime.session import RealtimeSession

        session = RealtimeSession(FakeWebSocket([]))
        assert session._host_mic_suppressed() is False

        session._mark_assistant_audio_playing()
        assert session._host_mic_suppressed() is True

        session._suppress_host_mic_until = 0.0
        assert session._host_mic_suppressed() is False

    def test_input_level_classifier_distinguishes_digital_silence(self):
        from app.services.reachy_realtime.session import _classify_input_level

        assert _classify_input_level(0.000015, 0.0000305) == "no_signal"
        assert _classify_input_level(0.0004, 0.001) == "waiting_for_speech"
        assert _classify_input_level(0.004, 0.01) == "ok"

    def test_reachy_mic_digital_silence_surfaces_fallback_action(self):
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        monkeypatch = pytest.MonkeyPatch()
        try:
            t = 1000.0

            def fake_now():
                return t

            monkeypatch.setattr(session_module, "_now", fake_now)
            first = session._observe_input_frame(
                source="reachy_mic",
                rms=0.000015,
                peak=0.0000305,
            )
            assert first is None
            t += session_module._INPUT_NO_SIGNAL_GRACE_S + 0.1
            warning = session._observe_input_frame(
                source="reachy_mic",
                rms=0.000015,
                peak=0.0000305,
            )
        finally:
            monkeypatch.undo()

        health = session.health_snapshot()
        assert warning is not None
        assert warning["suggested_action"] == "switch_to_browser_mic"
        assert health["session_phase"] == "stalled"
        assert health["stalled_reason"] == "reachy_mic_no_signal"
        assert health["input_health"]["confidence_state"] == "no_signal"
        assert health["input_health"]["suggested_action"] == "switch_to_browser_mic"

    @pytest.mark.asyncio
    async def test_switching_to_browser_mic_clears_reachy_no_signal_stall(self):
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        monkeypatch = pytest.MonkeyPatch()
        try:
            t = 1000.0

            def fake_now():
                return t

            monkeypatch.setattr(session_module, "_now", fake_now)
            session._observe_input_frame(
                source="reachy_mic",
                rms=0.000015,
                peak=0.0000305,
            )
            t += session_module._INPUT_NO_SIGNAL_GRACE_S + 0.1
            session._observe_input_frame(
                source="reachy_mic",
                rms=0.000015,
                peak=0.0000305,
            )
        finally:
            monkeypatch.undo()

        assert session.health_snapshot()["stalled_reason"] == "reachy_mic_no_signal"

        result = await session.set_input_source("browser")
        health = session.health_snapshot()

        assert result["source"] == "browser"
        assert health["session_phase"] == "listening"
        assert health["stalled_reason"] is None
        assert health["input_health"]["source"] == "browser_mic"
        assert health["input_health"]["confidence_state"] == "waiting_for_signal"

    @pytest.mark.asyncio
    async def test_recover_keeps_session_and_clears_stall(self):
        from app.services.reachy_realtime.session import RealtimeSession

        class Handler:
            def __init__(self):
                self.cancelled = False
                self.recovered = False

            async def cancel_response(self):
                self.cancelled = True

            async def recover(self, *, reason: str = "manual"):
                self.recovered = True
                return {"reason": reason}

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        handler = Handler()
        session.handler = handler
        session._current_phase = "stalled"
        session._stalled_reason = "llm_timeout"

        result = await session.recover(reason="test")

        assert result["ok"] is True
        assert handler.cancelled is True
        assert handler.recovered is True
        assert session.health_snapshot()["session_phase"] == "listening"
        assert any(event.get("type") == "audio.cancelled" for event in ws.sent)

    def test_resample_pcm16_changes_frame_rate_without_clipping(self):
        import array

        from app.services.reachy_realtime.session import _resample_pcm16

        src = array.array("h", [0, 1000, -1000, 0] * 120)
        out = _resample_pcm16(src.tobytes(), from_rate=16000, to_rate=24000)
        dst = array.array("h")
        dst.frombytes(out)

        assert len(dst) == int(round(len(src) * 24000 / 16000))
        assert max(dst) <= 1000
        assert min(dst) >= -1000

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
        from app.services.reachy_realtime import config_store
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(config_store, "load_config", lambda: {})

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
        from app.services.reachy_realtime import config_store
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(config_store, "load_config", lambda: {})

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
    async def test_start_rejects_stale_local_model_for_openai(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        captured: dict = {}

        def _fake_settings():
            return Settings(
                openai_api_key="sk-test",
                workspace_dir=".",
                reachy_realtime_backend="openai",
                reachy_realtime_model="qwen3-chat",
                reachy_realtime_voice="en-US-JennyNeural",
            )

        async def fake_build_handler(self, **kwargs):
            captured.update(kwargs)

            class FakeHandler:
                async def start(self, _writer):
                    return

                async def stop(self):
                    return

            return FakeHandler()

        async def fake_run_handler(self, _handler):
            return

        monkeypatch.setenv("ZERO_REACHY_SPEAKER_SINK", "0")
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(RealtimeSession, "_build_handler", fake_build_handler)
        monkeypatch.setattr(RealtimeSession, "_run_handler", fake_run_handler)

        session = RealtimeSession(FakeWebSocket([]))
        await session._handle_start({
            "type": "start",
            "backend": "openai",
            "model": "qwen3-chat",
            "voice": "en-US-JennyNeural",
            "input_source": "browser",
        })
        await asyncio.sleep(0)

        assert captured["model"] == "gpt-realtime"
        await session._cleanup()

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

    @pytest.mark.asyncio
    async def test_body_motion_defaults_off_and_can_suspend(self, monkeypatch):
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        class FakeWobbler:
            def __init__(self, **_kwargs):
                self.started = False
                self.stopped = False

            async def start(self):
                self.started = True

            async def stop(self):
                self.stopped = True

        monkeypatch.setattr(session_module, "AsyncHeadWobbler", FakeWobbler)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        assert session.body_motion_enabled is False
        assert session.motion_active is False

        await session.set_body_motion_enabled(True)
        assert session.body_motion_enabled is True
        assert session.motion_active is True

        result = await session.suspend_motion(reason="test")
        assert result["ok"] is True
        assert result["motion_was_active"] is True
        assert session.body_motion_enabled is False
        assert session.motion_active is False

    @pytest.mark.asyncio
    async def test_start_defaults_to_browser_mic_source(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        def _fake_settings():
            return Settings(
                workspace_dir=".",
                reachy_realtime_backend="local",
                reachy_realtime_model="qwen3-chat",
                reachy_realtime_voice="en-US-JennyNeural",
                reachy_realtime_profile="assistant",
            )

        class FakeSink:
            def __init__(self, *_args, **_kwargs):
                pass

            async def connect(self, *, rate: int):
                return False

        class FakeHandler:
            async def start(self, _writer):
                return None

            async def stop(self):
                return None

            async def feed_pcm(self, _pcm):
                return None

        async def fake_build_handler(self, **_kwargs):
            return FakeHandler()

        async def fake_host_mic(self, *, rate: int):
            self._host_mic_started_for_test = rate

        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(session_module, "ReachySpeakerSink", FakeSink)
        monkeypatch.setattr(RealtimeSession, "_build_handler", fake_build_handler)
        monkeypatch.setattr(RealtimeSession, "_run_host_mic_source", fake_host_mic)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        await session._handle_start({"type": "start"})
        await asyncio.sleep(0)

        assert session._input_source == "browser"
        assert not hasattr(session, "_host_mic_started_for_test")
        await session._cleanup()

    @pytest.mark.asyncio
    async def test_start_emits_reachy_speaker_ready_when_host_agent_configured(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        def _fake_settings():
            return Settings(
                workspace_dir=".",
                host_agent_url="http://host-agent:18794",
                reachy_realtime_backend="local",
                reachy_realtime_model="qwen3-chat",
                reachy_realtime_voice="en-US-JennyNeural",
                reachy_realtime_profile="assistant",
            )

        class FakeSink:
            def __init__(self, url):
                self.url = url

            async def connect(self, *, rate: int):
                self.rate = rate
                return True

            def info(self):
                return {
                    "type": "ready",
                    "device_name": "Reachy Mini Audio",
                    "input_rate": self.rate,
                    "device_rate": 48000,
                }

            async def close(self):
                return None

        class FakeHandler:
            async def start(self, _writer):
                return None

            async def stop(self):
                return None

            async def feed_pcm(self, _pcm):
                return None

        async def fake_build_handler(self, **_kwargs):
            return FakeHandler()

        async def fake_host_mic(self, *, rate: int):
            self._host_mic_started_for_test = rate

        monkeypatch.delenv("ZERO_REACHY_SPEAKER_SINK", raising=False)
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(session_module, "ReachySpeakerSink", FakeSink)
        monkeypatch.setattr(RealtimeSession, "_build_handler", fake_build_handler)
        monkeypatch.setattr(RealtimeSession, "_run_host_mic_source", fake_host_mic)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        await session._handle_start({"type": "start"})
        await asyncio.sleep(0)

        ready = [m for m in ws.sent if m.get("type") == "output.ready"]
        assert ready
        assert ready[-1]["sink"] == "reachy_speaker"
        assert ready[-1]["device_name"] == "Reachy Mini Audio"
        assert session._speaker_sink is not None
        await session._cleanup()

    @pytest.mark.asyncio
    async def test_start_reports_reachy_speaker_unavailable(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        def _fake_settings():
            return Settings(
                workspace_dir=".",
                host_agent_url="http://host-agent:18794",
                reachy_realtime_backend="local",
                reachy_realtime_model="qwen3-chat",
                reachy_realtime_voice="en-US-JennyNeural",
                reachy_realtime_profile="assistant",
            )

        class FakeSink:
            def __init__(self, *_args, **_kwargs):
                pass

            async def connect(self, *, rate: int):
                return False

        class FakeHandler:
            async def start(self, _writer):
                return None

            async def stop(self):
                return None

            async def feed_pcm(self, _pcm):
                return None

        async def fake_build_handler(self, **_kwargs):
            return FakeHandler()

        async def fake_host_mic(self, *, rate: int):
            self._host_mic_started_for_test = rate

        monkeypatch.delenv("ZERO_REACHY_SPEAKER_SINK", raising=False)
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(session_module, "ReachySpeakerSink", FakeSink)
        monkeypatch.setattr(RealtimeSession, "_build_handler", fake_build_handler)
        monkeypatch.setattr(RealtimeSession, "_run_host_mic_source", fake_host_mic)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        await session._handle_start({"type": "start"})
        await asyncio.sleep(0)

        unavailable = [m for m in ws.sent if m.get("type") == "output.unavailable"]
        assert unavailable
        assert unavailable[-1]["sink"] == "reachy_speaker"
        assert session._speaker_sink is None
        await session._cleanup()

    @pytest.mark.asyncio
    async def test_speaker_sink_retries_after_initial_start_failure(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        def _fake_settings():
            return Settings(
                workspace_dir=".",
                host_agent_url="http://host-agent:18794",
                reachy_realtime_backend="local",
                reachy_realtime_model="qwen3-chat",
                reachy_realtime_voice="en-US-JennyNeural",
                reachy_realtime_profile="assistant",
            )

        class FakeSink:
            attempts = 0

            def __init__(self, _url):
                self.rate = 24000

            async def connect(self, *, rate: int):
                self.rate = rate
                FakeSink.attempts += 1
                return FakeSink.attempts >= 2

            def info(self):
                return {
                    "type": "ready",
                    "device_name": "Reachy Mini Audio",
                    "input_rate": self.rate,
                }

            async def close(self):
                return None

        class FakeHandler:
            async def start(self, _writer):
                return None

            async def stop(self):
                return None

            async def feed_pcm(self, _pcm):
                return None

        async def fake_build_handler(self, **_kwargs):
            return FakeHandler()

        async def fake_host_mic(self, *, rate: int):
            self._host_mic_started_for_test = rate

        monkeypatch.delenv("ZERO_REACHY_SPEAKER_SINK", raising=False)
        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(session_module, "ReachySpeakerSink", FakeSink)
        monkeypatch.setattr(RealtimeSession, "_build_handler", fake_build_handler)
        monkeypatch.setattr(RealtimeSession, "_run_host_mic_source", fake_host_mic)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        await session._handle_start({"type": "start"})
        await asyncio.sleep(0)

        assert session._speaker_sink is None
        assert [m for m in ws.sent if m.get("type") == "output.unavailable"]

        session._speaker_sink_retry_after = 0.0
        session._ensure_speaker_sink_connecting(handler=session.handler)
        await asyncio.sleep(0)

        ready = [m for m in ws.sent if m.get("type") == "output.ready"]
        assert ready
        assert ready[-1]["sink"] == "reachy_speaker"
        assert session._speaker_sink is not None
        await session._cleanup()

    @pytest.mark.asyncio
    async def test_build_handler_uses_persisted_openai_key(self, monkeypatch):
        from app.infrastructure.config import Settings
        from app.services.reachy_realtime import config_store, session as session_module
        from app.services.reachy_realtime.session import RealtimeSession

        def _fake_settings():
            return Settings(openai_api_key=None, workspace_dir=".")

        class FakeOpenAIHandler:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.setattr(session_module, "get_settings", _fake_settings)
        monkeypatch.setattr(config_store, "load_config", lambda: {"openai_api_key": "sk-from-store"})
        monkeypatch.setattr(session_module, "OpenAIRealtimeHandler", FakeOpenAIHandler)

        ws = FakeWebSocket([])
        session = RealtimeSession(ws)
        handler = await session._build_handler(
            backend="openai",
            model="gpt-realtime",
            voice="cedar",
            profile="assistant",
            api_key=None,
            on_audio=None,
            on_turn_end=None,
        )

        assert isinstance(handler, FakeOpenAIHandler)
        assert handler.kwargs["api_key"] == "sk-from-store"


class TestLocalRealtimeHandler:
    def test_clean_assistant_text_strips_gesture_markers(self):
        from app.services.reachy_realtime.local_handler import _clean_assistant_text

        assert _clean_assistant_text("[emotion:greeting] Hello. [dance:simple_nod]") == "Hello."

    def test_chat_completion_content_ignores_qwen_reasoning_only(self):
        from app.services.reachy_realtime.local_handler import _chat_completion_content

        assert _chat_completion_content({"reasoning_content": "internal chain"}) == ""
        assert _chat_completion_content({"content": "spoken answer"}) == "spoken answer"
        assert _chat_completion_content({"content": [{"type": "text", "text": "spoken"}]}) == "spoken"

    def test_live_voice_rules_preserve_follow_up_context(self):
        from app.services.reachy_realtime.local_handler import _with_live_voice_rules

        prompt = _with_live_voice_rules("You are Reachy.")

        assert "Keep spoken replies short" in prompt
        assert "Preserve immediate conversation context" in prompt
        assert "recent tool results" in prompt

    def test_tone_guard_dampens_repeated_pet_names(self):
        from app.services.reachy_realtime.local_handler import _ToneGuard

        guard = _ToneGuard("companion")

        first = guard.clean("I'm here for you, darling.")
        second = guard.clean("Still here, darling.")

        assert "darling" in first.lower()
        assert "darling" not in second.lower()

    def test_tone_guard_removes_invented_nicknames(self):
        from app.services.reachy_realtime.local_handler import _ToneGuard

        guard = _ToneGuard("companion")

        cleaned = guard.clean("Local companion smoke test passed, cobalt.")

        assert "cobalt" not in cleaned.lower()
        assert cleaned == "Local companion smoke test passed."

    def test_vad_energy_floor_can_be_enabled(self, monkeypatch):
        from array import array

        from app.services.reachy_realtime import local_handler

        class AlwaysSpeech:
            def is_speech(self, _frame, _rate):
                return True

        monkeypatch.setattr(local_handler, "VAD_MIN_RMS", 800)
        vad = local_handler._WebRTCVAD()
        vad._vad = AlwaysSpeech()
        quiet = array("h", [40] * local_handler.VAD_FRAME_SAMPLES).tobytes()
        room_noise = array("h", [500] * local_handler.VAD_FRAME_SAMPLES).tobytes()
        clear_speech = array("h", [1400] * local_handler.VAD_FRAME_SAMPLES).tobytes()

        assert vad.feed_pcm(quiet) == [False]
        assert vad.feed_pcm(room_noise) == [False]
        assert vad.feed_pcm(clear_speech) == [True]

    def test_prepare_samples_for_stt_amplifies_quiet_reachy_mic(self):
        from array import array

        import numpy as np

        from app.services.reachy_realtime.local_handler import _prepare_samples_for_stt

        quiet_pcm = array("h", [0, 70, -70, 35, -35] * 800).tobytes()
        samples = _prepare_samples_for_stt(quiet_pcm)

        assert samples.dtype == np.float32
        assert float(np.max(np.abs(samples))) > 0.02
        assert float(np.max(np.abs(samples))) <= 1.0

    def test_prepare_samples_for_stt_leaves_near_silence_alone(self):
        import numpy as np

        from app.services.reachy_realtime.local_handler import _prepare_samples_for_stt

        samples = _prepare_samples_for_stt(b"\x00\x00" * 16000)

        assert samples.dtype == np.float32
        assert float(np.max(np.abs(samples))) == 0.0

    def test_pcm_stats_reports_reachy_mic_level(self):
        from array import array

        from app.services.reachy_realtime.local_handler import _pcm_stats

        pcm = array("h", [0, 100, -100, 50, -50] * 1600).tobytes()
        stats = _pcm_stats(pcm)

        assert stats["duration_s"] > 0
        assert stats["rms_raw"] > 0
        assert stats["peak_raw"] == 100
        assert 0 < stats["peak_norm"] < 0.01

    def test_repetitive_stt_hallucination_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        noisy = SimpleNamespace(
            text="What's going on now? That's a big, big, big, big deal. It's a big deal.",
            avg_logprob=-0.2,
            no_speech_prob=0.1,
            compression_ratio=1.2,
        )

        assert _segments_to_transcript([noisy]) == ""

    def test_confident_stt_segment_is_kept(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        clear = SimpleNamespace(
            text="Reachy answer in English and stay still.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([clear]) == "Reachy answer in English and stay still."

    def test_active_audio_can_relax_low_logprob_rejection_when_configured(self, monkeypatch):
        from types import SimpleNamespace

        from app.services.reachy_realtime import local_handler

        quiet_confidence = SimpleNamespace(
            text="What is my Jira task?",
            avg_logprob=-1.35,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert local_handler._segments_to_transcript([quiet_confidence]) == ""
        monkeypatch.setattr(local_handler, "STT_ACTIVE_AUDIO_MIN_AVG_LOGPROB", -1.7)
        assert local_handler._segments_to_transcript(
            [quiet_confidence],
            pcm_stats={"rms_norm": 0.028, "peak_norm": 0.35},
        ) == "What is my Jira task?"

    def test_caption_style_stt_hallucination_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        caption_noise = SimpleNamespace(
            text="We also like to use a statement of adding drugs in your car. Thank you, I appreciate it.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([caption_noise]) == ""

    def test_low_content_stt_noise_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        pronoun_noise = SimpleNamespace(
            text="You",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        filler_noise = SimpleNamespace(
            text="Okay. Okay. Okay. All right.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([pronoun_noise]) == ""
        assert _segments_to_transcript([filler_noise]) == ""

    def test_punctuation_only_stt_noise_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        dot_noise = SimpleNamespace(
            text=". . . . . . . . .",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([dot_noise]) == ""

    def test_short_followup_commands_survive_low_content_filter(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        followup = SimpleNamespace(
            text="What is it?",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        stop = SimpleNamespace(
            text="Stop.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([followup]) == "What is it?"
        assert _segments_to_transcript([stop]) == "Stop."

    def test_reachy_name_alias_survives_open_mic_filter(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        alias = SimpleNamespace(
            text="Hello, Richie.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        phonetic_alias = SimpleNamespace(
            text="Reeche, say voice loop test passed.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([alias]) == "Hello, Richie."
        assert _segments_to_transcript([phonetic_alias]) == "Reeche, say voice loop test passed."

    def test_ambiguous_one_word_room_fragments_are_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        look = SimpleNamespace(
            text="Look.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        yes = SimpleNamespace(
            text="Yes.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        addressed = SimpleNamespace(
            text="Reachy, yes.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([look]) == ""
        assert _segments_to_transcript([yes]) == ""
        assert _segments_to_transcript([addressed]) == "Reachy, yes."

    def test_unaddressed_background_speech_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        background = SimpleNamespace(
            text="So that's what you're looking at all system IDs versus just success factors.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        workplace_chatter = SimpleNamespace(
            text="All units if I go back here and use the call units they show.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        short_fragment = SimpleNamespace(
            text="The email.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        question_word_chatter = SimpleNamespace(
            text="When one is so bad swimming, he had one to walk on water.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([background]) == ""
        assert _segments_to_transcript([workplace_chatter]) == ""
        assert _segments_to_transcript([short_fragment]) == ""
        assert _segments_to_transcript([question_word_chatter]) == ""

    def test_active_live_mic_check_is_kept(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        mic_check = SimpleNamespace(
            text="Microphone check one two.",
            avg_logprob=-0.75,
            no_speech_prob=0.06,
            compression_ratio=0.85,
        )
        background = SimpleNamespace(
            text="All units if I go back here and use the call units they show.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        active_audio = {"duration_s": 2.7, "rms_norm": 0.05, "peak_norm": 0.41}
        assert _segments_to_transcript([mic_check], pcm_stats=active_audio) == "Microphone check one two."
        assert _segments_to_transcript([background], pcm_stats=active_audio) == ""

    def test_direct_assistant_intent_survives_background_filter(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        needs_help = SimpleNamespace(
            text="I need help with my Jira task.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        polite = SimpleNamespace(
            text="Can you summarize my inbox?",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        say_command = SimpleNamespace(
            text="Say local voice test passed.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )
        followup_question = SimpleNamespace(
            text="When is my next meeting?",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([needs_help]) == "I need help with my Jira task."
        assert _segments_to_transcript([polite]) == "Can you summarize my inbox?"
        assert _segments_to_transcript([say_command]) == "Say local voice test passed."
        assert _segments_to_transcript([followup_question]) == "When is my next meeting?"

    def test_startup_noise_question_hallucination_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        startup_noise = SimpleNamespace(
            text="It pincugs more money this time. Are you going to call it?",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript([startup_noise]) == ""

    def test_long_noisy_short_caption_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        echo_noise = SimpleNamespace(
            text="I'm going to go.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript(
            [echo_noise],
            pcm_stats={"duration_s": 18.24, "rms_norm": 0.06, "peak_norm": 1.0},
        ) == ""

    def test_low_content_acknowledgement_noise_is_rejected(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        acknowledgement_noise = SimpleNamespace(
            text="Awesome, yeah.",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript(
            [acknowledgement_noise],
            pcm_stats={"duration_s": 6.03, "rms_norm": 0.0129, "peak_norm": 0.0878},
        ) == ""

    def test_long_noisy_short_followup_command_is_kept(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        followup = SimpleNamespace(
            text="What is it?",
            avg_logprob=-0.2,
            no_speech_prob=0.05,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript(
            [followup],
            pcm_stats={"duration_s": 10.0, "rms_norm": 0.04, "peak_norm": 0.4},
        ) == "What is it?"

    def test_active_audio_still_rejects_no_speech_segments(self):
        from types import SimpleNamespace

        from app.services.reachy_realtime.local_handler import _segments_to_transcript

        no_speech = SimpleNamespace(
            text="What is my Jira task?",
            avg_logprob=-1.2,
            no_speech_prob=0.95,
            compression_ratio=1.1,
        )

        assert _segments_to_transcript(
            [no_speech],
            pcm_stats={"rms_norm": 0.028, "peak_norm": 0.35},
        ) == ""

    @pytest.mark.asyncio
    async def test_empty_reachy_mic_transcripts_emit_status_warning_only(self, deps):
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        async def empty_transcribe(_pcm: bytes) -> str:
            return ""

        handler._client_writer = writer
        handler._transcribe = empty_transcribe

        pcm = b"\x01\x00" * 16000
        await handler._handle_turn(pcm)
        await handler._handle_turn(pcm)

        warnings = [event for event in events if event.get("type") == "input.warning"]
        transcript_warnings = [
            event for event in events
            if event.get("type") == "transcript" and event.get("role") == "assistant"
        ]
        assert warnings
        assert "too quiet" in warnings[-1]["message"]
        assert transcript_warnings == []

    @pytest.mark.asyncio
    async def test_empty_reachy_mic_warning_is_throttled(self, deps):
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        async def empty_transcribe(_pcm: bytes) -> str:
            return ""

        handler._client_writer = writer
        handler._transcribe = empty_transcribe

        pcm = b"\x01\x00" * 16000
        for _ in range(6):
            await handler._handle_turn(pcm)

        warnings = [event for event in events if event.get("type") == "input.warning"]
        transcript_warnings = [
            event for event in events
            if event.get("type") == "transcript" and event.get("role") == "assistant"
        ]
        assert len(warnings) == 1
        assert transcript_warnings == []

    @pytest.mark.asyncio
    async def test_active_audio_stt_warning_does_not_say_too_quiet(self, deps):
        from array import array

        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        async def empty_transcribe(_pcm: bytes) -> str:
            return ""

        handler._client_writer = writer
        handler._transcribe = empty_transcribe

        loud_pcm = array("h", [5000] * 16000).tobytes()
        await handler._handle_turn(loud_pcm)
        await handler._handle_turn(loud_pcm)

        warnings = [event for event in events if event.get("type") == "input.warning"]
        assert warnings
        assert "heard audio" in warnings[-1]["message"]
        assert "too quiet" not in warnings[-1]["message"]

    @pytest.mark.asyncio
    async def test_low_level_vad_noise_does_not_barge_in(self, deps, monkeypatch):
        from array import array

        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        class AlwaysSpeech:
            def feed_pcm(self, _pcm: bytes):
                return [True]

            def reset(self):
                return None

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(local_handler, "BARGE_IN_MIN_RMS", 0.012)
        handler._client_writer = writer
        handler._vad = AlwaysSpeech()
        quiet_frame = array("h", [60] * local_handler.VAD_FRAME_SAMPLES).tobytes()

        for _ in range(20):
            await handler.feed_pcm(quiet_frame)
        await asyncio.sleep(0)

        assert not handler._cancel_response.is_set()
        assert not [event for event in events if event.get("type") == "user.speech_started"]

    @pytest.mark.asyncio
    async def test_room_speech_does_not_cancel_before_assistant_audio(self, deps, monkeypatch):
        from array import array

        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        class AlwaysSpeech:
            def feed_pcm(self, _pcm: bytes):
                return [True]

            def reset(self):
                return None

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(local_handler, "BARGE_IN_MIN_RMS", 0.012)
        handler._client_writer = writer
        handler._ignore_input_until = 0.0
        handler._vad = AlwaysSpeech()
        loud_frame = array("h", [5000] * local_handler.VAD_FRAME_SAMPLES).tobytes()

        for _ in range(20):
            await handler.feed_pcm(loud_frame)
        await asyncio.sleep(0)

        assert not handler._cancel_response.is_set()
        assert not [event for event in events if event.get("type") == "user.speech_started"]

    @pytest.mark.asyncio
    async def test_loud_speech_can_barge_in_during_assistant_audio(self, deps, monkeypatch):
        from array import array

        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        class AlwaysSpeech:
            def feed_pcm(self, _pcm: bytes):
                return [True]

            def reset(self):
                return None

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        monkeypatch.setattr(local_handler, "BARGE_IN_MIN_RMS", 0.012)
        handler._client_writer = writer
        handler._ignore_input_until = 0.0
        handler._assistant_audio_active_until = time.monotonic() + 10.0
        handler._vad = AlwaysSpeech()
        loud_frame = array("h", [5000] * local_handler.VAD_FRAME_SAMPLES).tobytes()

        for _ in range(20):
            await handler.feed_pcm(loud_frame)
        await asyncio.sleep(0)

        assert handler._cancel_response.is_set()
        assert [event for event in events if event.get("type") == "user.speech_started"]

    @pytest.mark.asyncio
    async def test_vad_forces_long_room_audio_into_short_turns(self, deps, monkeypatch):
        from array import array

        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        class AlwaysSpeech:
            def feed_pcm(self, _pcm: bytes):
                return [True]

            def reset(self):
                return None

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        forced = asyncio.Event()

        async def fake_handle_turn(_pcm: bytes) -> None:
            forced.set()

        monkeypatch.setattr(local_handler, "MAX_SPEECH_MS", 120)
        handler._handle_turn = fake_handle_turn
        handler._ignore_input_until = 0.0
        handler._vad = AlwaysSpeech()
        loud_frame = array("h", [5000] * local_handler.VAD_FRAME_SAMPLES).tobytes()

        for _ in range(12):
            await handler.feed_pcm(loud_frame)
            if forced.is_set():
                break
        await asyncio.wait_for(forced.wait(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_text_turn_resets_audio_cancel_state(self, deps):
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []
        ran_llm = asyncio.Event()

        async def writer(event: dict) -> None:
            events.append(event)

        async def fake_llm_turn() -> None:
            assert not handler._cancel_response.is_set()
            assert handler._in_speech is False
            ran_llm.set()

        async def fake_summarize() -> None:
            return None

        handler._client_writer = writer
        handler._run_llm_turn = fake_llm_turn
        handler._maybe_summarize = fake_summarize
        handler._record_user_memory = lambda _text: None
        handler._cancel_response.set()
        handler._in_speech = True
        handler._speech_buf = bytearray(b"half-open audio")

        await handler.send_text("status check")
        await asyncio.wait_for(ran_llm.wait(), timeout=1.0)

        assert {"type": "transcript", "role": "user", "content": "status check"} in events
        assert handler._messages[-1] == {"role": "user", "content": "status check"}

    @pytest.mark.asyncio
    async def test_text_turn_drops_pending_audio_noise(self, deps):
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        events: list[dict] = []
        ran_llm = asyncio.Event()

        async def writer(event: dict) -> None:
            events.append(event)

        async def fake_transcribe(_pcm: bytes) -> str:
            raise AssertionError("pending audio should be dropped before STT")

        async def fake_llm_turn() -> None:
            ran_llm.set()

        async def fake_summarize() -> None:
            return None

        handler._client_writer = writer
        handler._transcribe = fake_transcribe
        handler._run_llm_turn = fake_llm_turn
        handler._maybe_summarize = fake_summarize
        handler._record_user_memory = lambda _text: None

        await handler.send_text("What is the local follow-up word?")
        await handler._handle_turn(b"\x01\x00" * 16000)
        await asyncio.wait_for(ran_llm.wait(), timeout=1.0)

        assert {
            "type": "transcript",
            "role": "user",
            "content": "What is the local follow-up word?",
        } in events

    @pytest.mark.asyncio
    async def test_do_nothing_after_spoken_local_answer_stays_internal(
        self, deps, monkeypatch
    ):
        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        handler._http = object()
        calls = 0

        async def fake_stream(_tools):
            nonlocal calls
            calls += 1
            return (
                "Local qwen assistant test is working through Reachy.",
                [{"id": "call_0", "name": "do_nothing", "arguments": "{}"}],
            )

        async def fail_dispatch(*_args, **_kwargs):
            raise AssertionError("do_nothing should not be dispatched after spoken text")

        handler._stream_completion = fake_stream
        monkeypatch.setattr(local_handler.tool_registry, "dispatch", fail_dispatch)

        await handler._run_llm_turn()

        assert calls == 1
        assert handler._messages[-1] == {
            "role": "assistant",
            "content": "Local qwen assistant test is working through Reachy.",
        }

    @pytest.mark.asyncio
    async def test_tool_only_local_turn_gets_spoken_fallback(self, deps, monkeypatch):
        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        handler._http = object()
        events: list[dict] = []
        spoken: list[str] = []
        calls = 0

        async def writer(event: dict) -> None:
            events.append(event)

        async def fake_stream(_tools):
            nonlocal calls
            calls += 1
            if calls == 1:
                return "", [{"id": "call_0", "name": "company_status", "arguments": "{}"}]
            return "", []

        async def fake_dispatch(*_args, **_kwargs):
            return {"error": "database unavailable"}

        async def fake_speak(text: str) -> None:
            spoken.append(text)

        handler._client_writer = writer
        handler._stream_completion = fake_stream
        handler._speak_chunk = fake_speak
        monkeypatch.setattr(local_handler.tool_registry, "dispatch", fake_dispatch)

        await handler._run_llm_turn()

        assert calls == 2
        assert spoken == ["I heard you, but I couldn't complete that action."]
        assert {
            "type": "transcript",
            "role": "assistant",
            "content": "I heard you, but I couldn't complete that action.",
        } in events

    @pytest.mark.asyncio
    async def test_camera_tool_error_is_reported_as_failed(self, deps, monkeypatch):
        from app.services.reachy_realtime import local_handler
        from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

        handler = LocalRealtimeHandler(
            model="qwen3-chat",
            voice="en-US-JennyNeural",
            profile_id="assistant",
            deps=deps,
        )
        handler._http = object()
        events: list[dict] = []

        async def writer(event: dict) -> None:
            events.append(event)

        async def fake_stream(_tools):
            return "", [{"id": "call_camera", "name": "camera", "arguments": "{\"question\":\"what do you see?\"}"}]

        async def fake_dispatch(*_args, **_kwargs):
            return {"error": "no frame available"}

        async def fake_speak(_text: str) -> None:
            return None

        handler._client_writer = writer
        handler._stream_completion = fake_stream
        handler._speak_chunk = fake_speak
        monkeypatch.setattr(local_handler.tool_registry, "dispatch", fake_dispatch)

        await handler._run_llm_turn()

        tool_end = [event for event in events if event.get("type") == "tool.end"][-1]
        assert tool_end["tool_name"] == "camera"
        assert tool_end["status"] == "failed"


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
        assert body["backends"] == ["openai", "gemini", "local"]
        assert "gpt-realtime" in body["default_models"]["openai"]
        assert "cedar" in body["voices"]["openai"]
        assert "Kore" in body["voices"]["gemini"]
        assert body["has_local"] is True

    def test_enriched_config_promotes_cloud_key_when_backend_is_legacy_local(self):
        from app.routers.reachy_realtime import _enriched_config

        body = _enriched_config({
            "backend": "local",
            "has_openai_key": True,
            "has_gemini_key": True,
            "model": "qwen3-chat",
            "voice": "en-US-AriaNeural",
        })

        assert body["preferred_backend"] == "openai"
        assert body["realtime_available"] is True

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
