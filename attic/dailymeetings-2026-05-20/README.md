# DailyMeetings — archived 2026-05-20

## Why retired

This standalone Windows-host FastAPI service (formerly `C:\code\DailyMeetings\`, port 18793) duplicated capability that has since been ported into Zero's main backend. Maintaining two parallel meeting pipelines — two Whisper engines, two transcript stores, two Ollama callers, two sets of routers — created drift between recordings opened in DailyMeetings vs Zero. Retiring it eliminates the split brain.

Sprint: **Feature-12: Meeting capture convergence**.

## Where each capability now lives in Zero

All 13 DailyMeetings services have functional equivalents inside `backend/app/services/` as `meeting_*` modules:

| DailyMeetings module | Zero equivalent |
| --- | --- |
| `services/audio_capture.py` | `backend/app/services/meeting_audio_capture.py` (pyaudiowpatch WASAPI loopback + sounddevice Reachy mic) |
| `services/audio_buffer.py` | `backend/app/services/meeting_audio_buffer.py` |
| `services/recording_service.py` | `backend/app/services/meeting_recording_service.py` |
| `services/transcription_service.py` | `backend/app/services/meeting_transcription_service.py` |
| `services/live_transcription_service.py` | `host_agent/live_transcription.py` (Whisper streaming over the WS `/ws/meeting-live-transcript`) |
| `services/diarization_service.py` | `backend/app/services/meeting_diarization_service.py` |
| `services/summary_service.py` | `backend/app/services/meeting_summary_service.py` |
| `services/vector_service.py` | `backend/app/services/meeting_vector_service.py` |
| `services/search_service.py` | `backend/app/services/meeting_search_service.py` |
| `services/rag_service.py` | `backend/app/services/meeting_rag_service.py` |
| `services/processing_pipeline.py` | `backend/app/services/meeting_processing_pipeline.py` |
| `services/whisper_compat.py` | Replaced by `faster-whisper` direct calls (distil-large-v3 default per `.claude/rules/50-llm.md`) |
| `routers/recordings.py` etc. | `backend/app/routers/meetings.py`, `meeting_recordings.py`, `meeting_summaries.py`, `meeting_search.py`, `meeting_chat.py` |

## Routing today

`frontend/nginx.conf` already proxies `/api/(meetings|meeting-recordings|meeting-transcriptions|meeting-summaries|meeting-search|meeting-chat)/*` to `zero-api:18792`. WebSockets:

- `/ws/meeting-recording` → `host_agent:18796` (owns mic + recording status)
- `/ws/meeting-live-transcript` → `host_agent:18796` (owns the Whisper streaming loop)
- `/ws/meeting-processing` → `zero-api:18792` (owns the post-meeting pipeline)

There is no reason for any caller to hit `localhost:18793` anymore.

## Resurrecting (if you ever need to)

Don't. If a capability looks missing in Zero, port it in instead. If you genuinely need to compare behavior, you can boot this archive with:

```powershell
cd attic/dailymeetings-2026-05-20
venv\Scripts\python run.py
```

But you'll need to remap database (it shared Zero's PG on host port 5433) and Ollama bindings. Treat this as a read-only reference, not a runtime.
