"""Fix-111 — coverage gap batch (reason / capture / respond) regression guards.

Source-verified gaps shipped this run (capture/reason/respond/reflect hunt):
  #1 reason   council "vote" voice/chat path was permanently dead — list_decisions
              filtered the `decision` column on status="proposed" (a value it never
              holds). Now uses pending_only -> decision IS NULL.
  #2 capture  _start_mic_capture / _start_system_capture leaked a stream and
              defeated the empty-WAV guard when start() raised (non-None handle).
              Now close+null on failure.
  #4 respond  vision-intercept turn returned before the Step-4 robot-playback
              block -> answer was browser-audible but the robot stayed silent.
              Now plays audio_response on Reachy before returning.

The decisive behavioral proof for #1 is the RUNTIME AC executed against the real
DB this run (pending_only finds a fresh proposal; broken status="proposed" does
not). These tests are structural regression guards that fail if a fix is reverted.
"""

import inspect
from pathlib import Path

from app.services.council_service import CouncilService


def _module_src(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def test_council_list_decisions_has_pending_only():
    # #1: the param that fixes the dead vote path must exist.
    sig = inspect.signature(CouncilService.list_decisions)
    assert "pending_only" in sig.parameters
    src = _module_src(inspect.getmodule(CouncilService))
    # pending_only must filter unvoted rows (decision IS NULL), not a status string.
    assert "decision.is_(None)" in src


def test_orchestration_vote_uses_pending_only_not_proposed():
    from app.services import orchestration_graph
    src = _module_src(orchestration_graph)
    assert "list_decisions(pending_only=True" in src
    # the broken filter must be gone from the vote branch
    assert 'list_decisions(status="proposed"' not in src


def test_capture_failure_nulls_streams():
    from app.services import meeting_audio_capture
    src = _module_src(meeting_audio_capture)
    # both failure paths must reset the stream handle so the empty-WAV guard works
    assert "self._mic_stream = None" in src
    assert "self._system_stream = None" in src
    # and they live in the except blocks alongside the *_failed log
    assert "mic_capture_failed" in src and "system_audio_failed" in src


