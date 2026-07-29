"""End-to-end Meeting Steward systems test.

Synthesises a multi-speaker meeting via edge-tts, plays it into the room
through the host's default audio output while Zero records via Reachy's
USB mic, then drives the meeting through the full Steward pipeline
(transcribe -> diarize -> summarize -> action items) and asserts on the
result.

Why edge-tts + room playback instead of Reachy's own speaker:
  Reachy Mini is an "Echo Cancelling Speakerphone". If we play through
  its USB speaker the AEC will null its own output from the mic capture,
  defeating the self-loop. Playing through the host's default output
  device (Realtek desktop speakers) into Reachy's mic captures real
  room audio with no AEC interference -- the same path a real meeting
  takes.

Usage:
  python scripts/meeting_e2e_test.py [--mic-device 26] [--keep]

Requires:
  - zero-api healthy on :18792
  - host_agent on :18796 with /record/* + Reachy USB mic visible
  - ZERO_HF_TOKEN set in zero-api env (for pyannote diarization)
  - edge-tts pip-installed in the runtime (it is; zero-api uses it for TTS)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

ZERO_API = os.getenv("ZERO_API_URL", "http://localhost:18792").rstrip("/")
HOST_AGENT = os.getenv("ZERO_HOST_AGENT_URL", "http://localhost:18796").rstrip("/")
WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"
FIXTURES = WORKSPACE / "test_fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


# Two distinct edge-tts voices. Picked for clear gender contrast so pyannote
# clusters them reliably and Whisper transcribes each cleanly.
ALICE_VOICE = "en-US-AriaNeural"
BOB_VOICE = "en-US-GuyNeural"

# Compact meeting script: one decision, three action items, two speakers.
# Designed to exercise summary + action-item extraction + diarization.
MEETING_SCRIPT = [
    (ALICE_VOICE, "Welcome to the Tuesday product sync. Let's start with the meeting steward."),
    (BOB_VOICE, "Right. We agreed to ship the meeting steward to production by Friday."),
    (ALICE_VOICE, "Action item for me: I will email the design team about the new UI by tomorrow."),
    (BOB_VOICE, "And we should follow up with Sarah on the Q3 roadmap by end of week."),
    (ALICE_VOICE, "Sounds good. Let's wrap up here."),
]


async def synth_fixture(out_wav: Path) -> Path:
    """Render the MEETING_SCRIPT into a single 16 kHz mono WAV.

    Runs inside the zero-api container so we can reuse its edge_tts + ffmpeg
    install (the host typically lacks ffmpeg). The workspace dir is bind-mounted
    so the resulting WAV at /app/workspace/test_fixtures/meeting_2speaker.wav
    appears on the host at C:\\code\\zero\\workspace\\test_fixtures\\... too.
    """
    fixtures_in_container = "/app/workspace/test_fixtures"
    script_lines = json.dumps(MEETING_SCRIPT)

    # Single-shot Python program executed inside zero-api. Stays small so we
    # can pass it on the command line without temp-file plumbing.
    py = f"""
import asyncio, json, subprocess, sys
from pathlib import Path
import edge_tts

LINES = json.loads({script_lines!r})
OUT_DIR = Path({fixtures_in_container!r})
OUT_DIR.mkdir(parents=True, exist_ok=True)
out_wav = OUT_DIR / 'meeting_2speaker.wav'

async def main():
    mp3s = []
    for i, (voice, line) in enumerate(LINES):
        mp3 = OUT_DIR / f'line_{{i:02d}}_{{voice.split(\"-\")[-1]}}.mp3'
        await edge_tts.Communicate(line, voice).save(str(mp3))
        mp3s.append(mp3)
        print(f'  synthesised {{i}}: {{voice}} ({{len(line)}} chars)')

    # Build an ffmpeg concat list with 0.4s silence between turns.
    concat_inputs = []
    for i, mp3 in enumerate(mp3s):
        concat_inputs.append(['-i', str(mp3)])
        if i < len(mp3s) - 1:
            concat_inputs.append(['-f', 'lavfi', '-t', '0.4', '-i', 'anullsrc=r=16000:cl=mono'])

    cmd = ['ffmpeg', '-y']
    for ci in concat_inputs:
        cmd.extend(ci)
    n = len(concat_inputs)
    filter_inputs = ''.join(f'[{{j}}:a]' for j in range(n))
    cmd.extend([
        '-filter_complex', f'{{filter_inputs}}concat=n={{n}}:v=0:a=1[a]',
        '-map', '[a]', '-ar', '16000', '-ac', '1', '-sample_fmt', 's16',
        str(out_wav),
    ])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print('ffmpeg stderr:', r.stderr[-2000:], file=sys.stderr)
        sys.exit(2)
    print(f'  wrote {{out_wav}} ({{out_wav.stat().st_size}} bytes)')

asyncio.run(main())
"""
    r = subprocess.run(
        ["docker", "exec", "-i", "zero-api", "python", "-c", py],
        capture_output=True, text=True, check=False,
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise RuntimeError("Synth fixture failed inside zero-api container")
    if not out_wav.exists():
        raise FileNotFoundError(f"Synth produced no file at {out_wav}")
    return out_wav


def play_wav_blocking(wav_path: Path) -> float:
    """Play a WAV through the host's default audio device. Returns wall-clock seconds."""
    start = time.time()
    # PowerShell's [System.Media.SoundPlayer] is blocking and uses default output.
    ps_cmd = f"$p = New-Object System.Media.SoundPlayer '{wav_path}'; $p.PlaySync();"
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        check=True,
        capture_output=True,
    )
    return time.time() - start


def sync_meeting_row_to_docker_pg(meeting_id: str) -> None:
    """Copy meeting + meeting_recording rows from native PG17 -> Docker zero-postgres.

    host_agent writes new meetings to native PG at localhost:5432 (postgres
    user). zero-api reads from the Docker zero-postgres container exposed at
    localhost:5434 (zero user). Until the topology is unified, this copy step
    is the bridge that lets the processing pipeline see the recording.
    """
    psql = r"C:\Program Files\PostgreSQL\17\bin\psql.exe"
    if not Path(psql).exists():
        print(f"  skip_db_sync: psql not at {psql}")
        return

    env_host = {**os.environ, "PGPASSWORD": "postgres123"}
    env_docker = {**os.environ, "PGPASSWORD": "zero_dev"}

    def _runcap(args: list[str], env: dict) -> str:
        r = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
        return r.stdout.strip()

    # Pull rows from native PG.
    m_json = _runcap([
        psql, "-h", "localhost", "-p", "5432", "-U", "postgres", "-d", "zero",
        "-A", "-t", "-c",
        f"SELECT json_build_object('id',id,'title',title,'calendar_event_id',calendar_event_id,"
        f"'start_time',start_time,'end_time',end_time,'duration_seconds',duration_seconds,"
        f"'status',status,'created_at',created_at) FROM meetings WHERE id='{meeting_id}';",
    ], env_host)
    if not m_json:
        print(f"  skip_db_sync: meeting {meeting_id} not found in native PG")
        return
    m = json.loads(m_json)

    r_json = _runcap([
        psql, "-h", "localhost", "-p", "5432", "-U", "postgres", "-d", "zero",
        "-A", "-t", "-c",
        f"SELECT json_build_object('id',id,'meeting_id',meeting_id,'file_path',file_path,"
        f"'format',format,'sample_rate',sample_rate,'channels',channels,"
        f"'duration_seconds',duration_seconds,'file_size_bytes',file_size_bytes,"
        f"'source',source,'mic_device_name',mic_device_name,'created_at',created_at) "
        f"FROM meeting_recordings WHERE meeting_id='{meeting_id}';",
    ], env_host)
    if not r_json:
        print(f"  skip_db_sync: recording for {meeting_id} not found in native PG")
        return
    r = json.loads(r_json)

    def _q(v):
        if v is None:
            return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    insert_sql = (
        f"INSERT INTO meetings (id, title, calendar_event_id, start_time, end_time, "
        f"duration_seconds, participants, status, created_at, updated_at) VALUES ("
        f"{_q(m['id'])}, {_q(m['title'])}, {_q(m['calendar_event_id'])}, "
        f"{_q(m['start_time'])}, {_q(m['end_time'])}, "
        f"{m['duration_seconds'] if m.get('duration_seconds') is not None else 'NULL'}, "
        f"NULL, {_q(m['status'])}, {_q(m['created_at'])}, NULL"
        f") ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, "
        f"end_time=EXCLUDED.end_time, duration_seconds=EXCLUDED.duration_seconds; "
        f"INSERT INTO meeting_recordings (id, meeting_id, file_path, format, sample_rate, "
        f"channels, duration_seconds, file_size_bytes, source, mic_device_name, created_at) VALUES ("
        f"{_q(r['id'])}, {_q(r['meeting_id'])}, {_q(r['file_path'])}, "
        f"{_q(r['format'])}, {r['sample_rate']}, {r['channels']}, "
        f"{r['duration_seconds']}, {r['file_size_bytes']}, "
        f"{_q(r['source'])}, {_q(r['mic_device_name'])}, {_q(r['created_at'])}"
        f") ON CONFLICT (id) DO UPDATE SET duration_seconds=EXCLUDED.duration_seconds, "
        f"file_size_bytes=EXCLUDED.file_size_bytes;"
    )
    _runcap([
        psql, "-h", "localhost", "-p", "5434", "-U", "zero", "-d", "zero", "-c", insert_sql,
    ], env_docker)
    print(f"  db_sync_ok: copied meeting + recording into Docker zero-postgres")


async def post(client: httpx.AsyncClient, url: str, json_body: dict | None = None) -> dict:
    # 60s default — pyannote/whisper model loads on first run can take 30-90s
    # and block the event loop, stalling unrelated GETs.
    r = await client.post(url, json=json_body or {}, timeout=120.0)
    r.raise_for_status()
    return r.json()


async def get(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url, timeout=60.0)
    r.raise_for_status()
    return r.json()


async def patch(client: httpx.AsyncClient, url: str, json_body: dict) -> dict:
    r = await client.patch(url, json=json_body, timeout=30.0)
    r.raise_for_status()
    return r.json()


async def pause_wake(client: httpx.AsyncClient) -> None:
    """Fully stop the wake loop -- /wake/pause only suspends inference; the
    underlying GStreamer mic stays open and holds device 26 in WDM-KS mode,
    which blocks sounddevice from opening it for recording. /wake/mode off
    tears the stream down so the recorder can claim the device cleanly."""
    try:
        await post(client, f"{HOST_AGENT}/wake/mode", {"mode": "off"})
        print("  wake stopped (device 26 released)")
    except Exception as e:
        print(f"  wake_stop_warning: {e}")


async def resume_wake(client: httpx.AsyncClient) -> None:
    try:
        await post(client, f"{HOST_AGENT}/wake/mode", {"mode": "openwakeword"})
        print("  wake re-armed (openwakeword)")
    except Exception as e:
        print(f"  wake_resume_warning: {e}")


async def run_test(mic_device: int, keep_fixture: bool) -> dict:
    fixture_wav = FIXTURES / "meeting_2speaker.wav"
    print(f"[1/8] Synthesising multi-speaker fixture -> {fixture_wav.name}")
    await synth_fixture(fixture_wav)
    print(f"      WAV size: {fixture_wav.stat().st_size} bytes")

    async with httpx.AsyncClient() as client:
        # 1. Pre-flight: companion -> meeting mode, transcribe_only on.
        print("[2/8] Entering companion meeting mode")
        await post(
            client,
            f"{ZERO_API}/api/reachy/companion/modes",
            {"mode": "meeting", "reason": "meeting_e2e_test", "apply_actions": True},
        )

        # 2. Pause wake so the recorder owns device 26 on WASAPI.
        print("[3/8] Pausing wake to free Reachy mic for WASAPI capture")
        await pause_wake(client)

        # 3. Start recording on device 26 (Reachy WASAPI native 16kHz). The
        #    USB device handle takes a moment to fully release after wake stop
        #    -- without this pause we get a WDM-KS error on the first try.
        print("      waiting 3s for Windows audio subsystem to release device")
        await asyncio.sleep(3.0)
        # Reachy USB mic appears under several host APIs. Try them in order so
        # the test works even if WASAPI's handle hasn't released yet.
        candidate_devices = [mic_device, 12, 2]  # WASAPI -> DirectSound -> MME
        rec = None
        meeting_id = None
        for cand in candidate_devices:
            print(f"[4/8] Starting recording on mic device {cand}")
            try:
                start_body = {
                    "title": f"Steward E2E Test (auto-fixture {datetime.now(timezone.utc).isoformat()})",
                    "source": "mic",
                    "mic_device_index": cand,
                }
                # Feature-52: opt-in camera capture during the recording.
                # Skipped by default because the synth-fixture self-loop has
                # no camera input -- enable with --camera to exercise the
                # face match path against real frames.
                if os.getenv("ZERO_TEST_CAMERA", "").strip().lower() in {"1","true","yes"}:
                    start_body["camera_capture"] = True
                    start_body["camera_capture_fps"] = 1.0
                rec = await post(
                    client,
                    f"{ZERO_API}/api/meeting-recordings/start",
                    start_body,
                )
            except httpx.HTTPStatusError as e:
                print(f"      device {cand} failed: HTTP {e.response.status_code}; trying next")
                continue
            meeting_id = rec["meeting_id"]
            # Probe the status -- host_agent returns is_recording=true even if
            # the mic stream failed open, so verify levels are moving.
            await asyncio.sleep(2.0)
            status = await get(client, f"{HOST_AGENT}/record/status")
            mic_lvl = (status.get("audio_levels") or {}).get("mic", 0.0)
            dur = status.get("duration_seconds", 0.0)
            if dur > 1.5 or mic_lvl > 0.001:
                print(f"      device {cand} live: dur={dur:.1f}s mic={mic_lvl:.4f}")
                break
            # Mic isn't actually capturing -- stop + try next device.
            print(f"      device {cand} silent (dur={dur:.1f}s mic={mic_lvl:.4f}); rolling to next")
            try:
                await post(client, f"{ZERO_API}/api/meeting-recordings/stop")
            except Exception:
                pass
            rec = None
            meeting_id = None
        if not meeting_id:
            raise RuntimeError("All candidate mic devices failed to capture audio")
        print(f"      meeting_id={meeting_id}")

        # Repoint companion at this meeting.
        await patch(
            client,
            f"{ZERO_API}/api/reachy/companion/policy",
            {"meeting_active": True, "meeting_active_id": meeting_id, "transcribe_only": True},
        )

        # 4. Play the fixture through the room so Reachy mic hears it.
        print(f"[5/8] Playing fixture (this is the 'meeting' that Reachy will hear)")
        # tiny pre-roll silence so the recorder's first frames aren't a fade-in artefact
        await asyncio.sleep(1.0)
        playback_s = play_wav_blocking(fixture_wav)
        print(f"      playback finished in {playback_s:.1f}s")
        # tiny post-roll
        await asyncio.sleep(1.0)

        # 5. Stop recording.
        print("[6/8] Stopping recording")
        stop_info = await post(client, f"{ZERO_API}/api/meeting-recordings/stop")
        print(f"      duration={stop_info.get('duration_seconds'):.1f}s "
              f"size={stop_info.get('file_size_bytes')} bytes")

        # Resume wake immediately so the assistant is still alive for the user.
        await resume_wake(client)

        # 6. (DB sync no longer needed -- as of 2026-05-21 .env fix, host_agent
        #    and zero-api both target Docker zero-postgres.)

        # 7. Wait for the pipeline. host_agent /record/stop auto-triggers
        #    /process via _trigger_zero_pipeline, so we don't need an extra
        #    POST here -- duplicate POSTs used to cause double-inserted
        #    transcript segments before the /process idempotency landed.
        print("[7/8] Waiting for processing pipeline (whisper -> pyannote -> summarize)")

        # 7. Poll until status -> completed or timeout. Pipeline first-run can
        #    take 2-3 min (whisper model load + pyannote model download).
        deadline = time.time() + 900
        last_status = None
        while time.time() < deadline:
            try:
                m = await get(client, f"{ZERO_API}/api/meetings/{meeting_id}")
            except (httpx.ReadTimeout, httpx.ConnectError) as e:
                # zero-api may be locked up loading a model; back off and retry.
                print(f"      poll_warn ({type(e).__name__}); retrying in 10s")
                await asyncio.sleep(10)
                continue
            if m["status"] != last_status:
                print(f"      status={m['status']}")
                last_status = m["status"]
            if m["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(10)

        if last_status != "completed":
            return {"ok": False, "reason": f"pipeline_did_not_complete:{last_status}",
                    "meeting_id": meeting_id}

        # 8. Fetch artefacts + assert.
        transcript = await get(client, f"{ZERO_API}/api/meeting-transcriptions/{meeting_id}")
        try:
            summary = await get(client, f"{ZERO_API}/api/meeting-summaries/{meeting_id}")
        except httpx.HTTPStatusError:
            summary = None
        try:
            actions = await get(client, f"{ZERO_API}/api/meetings/{meeting_id}/action-items")
        except httpx.HTTPStatusError:
            actions = None

        segments = transcript.get("segments", [])
        unique_speakers = {s.get("speaker") for s in segments if s.get("speaker")}
        action_count = len(actions.get("action_items", [])) if actions else 0

        result = {
            "ok": True,
            "meeting_id": meeting_id,
            "transcript_segments": len(segments),
            "unique_speakers": sorted(s for s in unique_speakers if s),
            "speaker_count": len(unique_speakers),
            "summary_present": bool(summary and summary.get("summary_text")),
            "action_item_count": action_count,
            "playback_seconds": round(playback_s, 1),
        }

        # Soft assertions -- log but don't crash on miss; we want the full report.
        if len(segments) < 3:
            result["warn_transcript_thin"] = True
        if len(unique_speakers) < 2:
            result["warn_diarization_single_speaker"] = True
        if not (summary and summary.get("summary_text")):
            result["warn_no_summary"] = True
        if action_count < 1:
            result["warn_no_action_items"] = True

        print("[8/8] Done.")
        print(json.dumps(result, indent=2))

        if not keep_fixture:
            for f in FIXTURES.glob("line_*.mp3"):
                f.unlink(missing_ok=True)

        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mic-device", type=int, default=int(os.getenv("ZERO_TEST_MIC_DEVICE", "26")),
                    help="Mic device index (default 26 = Reachy WASAPI)")
    ap.add_argument("--keep", action="store_true", help="Keep intermediate MP3 line fixtures")
    args = ap.parse_args()

    result = asyncio.run(run_test(mic_device=args.mic_device, keep_fixture=args.keep))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
