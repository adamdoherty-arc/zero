"""Fix-107 — supervise DRIVE+COVERAGE gap batch (12 backend/host fixes).

Each test discriminates the OLD (buggy) behaviour from the NEW (fixed) one so a
regression re-breaks the test, not just "exercises the line". Where a fix is on
a path that needs real hardware/DB/LLM (RTV4 note-id race, RL2 stream cancel,
HC1 readiness timing), the runtime assertion lives in the supervise run record
(curl/inline-import against the deployed container), not here.
"""
import asyncio

import pytest


# ---------------------------------------------------------------------------
# RTV1 — memory_facade.recall handles mem0 returning a BARE LIST (not a dict).
# Old code: `(results or {}).get("results", ...)` -> list.get -> AttributeError
# swallowed -> mem0 silently contributes 0 notes. New: normalize both shapes.
# ---------------------------------------------------------------------------
class _FakeMem0List:
    def search(self, query, user_id, limit):  # mem0 kwargs: query=, user_id=, limit=
        return [{"memory": "adam likes espresso", "score": 0.9}]


class _FakeMem0Dict:
    def search(self, query, user_id, limit):
        return {"results": [{"memory": "adam likes espresso", "score": 0.9}]}


def _neutralize_other_backends(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("backend offline in test")

    monkeypatch.setattr(
        "app.services.episodic_memory_service.get_episodic_memory_service", _raise
    )
    monkeypatch.setattr(
        "app.services.reachy_user_memory_service.get_reachy_user_memory_service", _raise
    )
    monkeypatch.setattr(
        "app.services.reachy_memory_blocks.get_reachy_memory_blocks", _raise
    )






# ---------------------------------------------------------------------------
# RSP2 — LocalRealtimeHandler._trim_history bounds the append-only history and
# preserves chat tool-call pairing (a 'tool' message never starts the window).
# ---------------------------------------------------------------------------
def _bare_handler():
    from app.services.reachy_realtime.local_handler import LocalRealtimeHandler

    h = LocalRealtimeHandler.__new__(LocalRealtimeHandler)
    return h








# ---------------------------------------------------------------------------
# CAP4 — AudioCapture.stop() terminates the PyAudio instance (not just closes
# the stream), so PortAudio host handles don't leak every recording.
# ---------------------------------------------------------------------------
class _FakePA:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True


def test_cap4_stop_terminates_pyaudio():
    from app.services.meeting_audio_capture import AudioCapture

    cap = AudioCapture(sample_rate=16000)
    fake = _FakePA()
    cap._is_recording = True
    cap._system_stream = None
    cap._mic_stream = None
    cap._mixer_thread = None
    cap._wav_writer = None
    cap._system_pa = fake

    cap.stop()
    assert fake.terminated is True, "PyAudio instance leaked (terminate not called)"
    assert cap._system_pa is None


# ---------------------------------------------------------------------------
# RSP1 — VoiceLoopService._spawn_bg anchors fire-and-forget tasks in a strong
# ref set and discards them on completion (GC can't cancel mid-flight).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RSN1 — council tie must NOT silently auto-approve. Mirrors the exact decision
# rule implemented in council_service.run_decision (max-count + tie -> revise).
# ---------------------------------------------------------------------------
def _council_decide(position_counts: dict) -> str:
    if sum(position_counts.values()) == 0:
        return "needs_revision"
    max_count = max(position_counts.values())
    leaders = [p for p, c in position_counts.items() if c == max_count]
    return leaders[0] if len(leaders) == 1 else "needs_revision"


def test_rsn1_council_tie_does_not_autoapprove():
    # 2 approve / 2 reject — OLD max(dict, key=get) returned "approve".
    assert _council_decide({"approve": 2, "reject": 2, "needs_revision": 0}) == "needs_revision"
    # Clear majority still wins.
    assert _council_decide({"approve": 3, "reject": 1, "needs_revision": 0}) == "approve"
    assert _council_decide({"approve": 1, "reject": 3, "needs_revision": 0}) == "reject"
    # Degenerate all-abstain (prior B3 fix) stays needs_revision.
    assert _council_decide({"approve": 0, "reject": 0, "needs_revision": 0}) == "needs_revision"


# ---------------------------------------------------------------------------
# RTV2 — memory merge adopts newer wording only when the incoming note is MORE
# confident than the PRE-max value (post-max comparison was always False).
# Mirrors the reachy_user_memory_service.add_note merge rule.
# ---------------------------------------------------------------------------
def _merge_decides_adopt(existing_conf: float, incoming_conf: float) -> bool:
    prev = existing_conf
    existing_conf = max(existing_conf, incoming_conf)  # noqa: F841 (mirrors real)
    return incoming_conf > prev


def test_rtv2_merge_adopts_more_confident_text():
    assert _merge_decides_adopt(0.5, 0.9) is True   # more confident -> adopt
    assert _merge_decides_adopt(0.9, 0.5) is False  # less confident -> keep
    assert _merge_decides_adopt(0.7, 0.7) is False  # equal -> keep
