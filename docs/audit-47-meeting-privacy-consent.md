# Audit-47 — Meeting privacy + consent enforcement

**Sprint:** Audit-47 (#5133)
**Date:** 2026-05-21
**Scope:** Verify `meeting_privacy_service.is_private()` actually gates downstream processing (LLM summary, vault writes, follow-up emails, RAG/vector index, task creation). Confirm `meeting_consent_service` prevents auto-record without consent.

---

## TL;DR

Consent gating at the recording-start boundary is solid. Privacy gating after the recording finishes had **two leaks** at the time of audit — both fixed in this sprint:

| Stage | Before | After |
|---|---|---|
| Auto-record consent gate | gated | gated (no change) |
| Auto-mark private from policy | applied | applied (no change) |
| Speaker diarization | unconditional (local only) | unconditional (local only) |
| **LLM summary generation** | **NOT GATED — leaked to LLM** | gated, skipped |
| RAG / vector-store indexing | NOT GATED | gated, skipped |
| Vault writer | gated (stub only) | gated (stub only) |
| Follow-up email drafts | gated | gated |
| Task auto-creation from action items | gated indirectly (no summary → no actions) | gated explicitly (private skips summary, so action items are empty) |

After this audit, a private meeting's transcript never leaves the user's host: no LLM call, no vector embedding, no vault write of content, no draft email, no task.

---

## Privacy flow — verified gates

### Recording entry-point (consent)

`scheduler_service._run_reachy_meeting_auto_record` (`backend/app/services/scheduler_service.py:2917`) calls `MeetingConsentService.evaluate(title, attendees)` before starting any recording:

- `deny` → mark skipped, no recording, no notification
- `ask` → publish `meeting.consent_needed` toast via the notification bus, mark skipped (user must explicitly hit "record now")
- `allow` → proceed

The consent policy (`workspace/meetings/consent_policy.json`) defaults to:

- `default_record_for_solo: true`
- `default_record_for_internal: true`
- `default_record_for_external: "ask"` ← critical guard for two-party-consent jurisdictions

`never_record_titles` and `always_record_titles` allow per-title overrides without code changes.

### Auto-private from policy

`scheduler_service` (`backend/app/services/scheduler_service.py:3061`) calls `MeetingPrivacyService.evaluate_default(title, attendees)` at recording start and auto-marks the meeting private when:

- The title contains any substring from `always_private_titles` (defaults: `["therapy", "doctor", "personal", "1:1 personal"]`)
- Any attendee email's domain matches `always_private_domains` (empty by default — user opt-in)

The recording itself still runs (so the user has a local copy), but every downstream propagation step now sees `is_private == True`.

### Vault writer (verified, was already correct)

`meeting_processing_pipeline.py:397` passes `private=get_meeting_privacy_service().is_private(meeting_id)` to `MeetingVaultWriter.write(...)`. The writer renders a stub-only vault note (title + timestamp) for private meetings rather than the full transcript / summary / action items.

### Follow-up emails (verified, was already correct)

`meeting_followup_service.py:111` early-returns with `{"ok": False, "reason": "private"}` before composing any draft. No LLM call, no email row created.

### Voice mark-private (verified, was already correct)

`reachy_realtime/tools.py:848` ships a `mark_meeting_private` tool exposed to Reachy. When the user says "this is private" during a live meeting, the tool calls `MeetingPrivacyService.mark_private(meeting_id, source="voice")` immediately — the flag is on by the time the pipeline kicks off after the recording stops.

---

## Gaps found AND fixed in this sprint

### Gap 1 — LLM summary leaked private transcripts

**Severity:** High. The summary step at `meeting_processing_pipeline.py:337` called `summary_svc.summarize(transcript_text, ...)` regardless of privacy state. If the active summary model is a cloud LLM (Bifrost/LiteLLM routing can include cloud backends), the user's "this is private" intent leaked: full transcript was POSTed to whatever provider answered.

**Fix:** Wrapped summary block in `if is_private:` guard at `meeting_processing_pipeline.py:340-348`. Private meetings now:

- Skip the LLM call entirely
- Stamp `result["steps"]["summarization"] = {"skipped": True, "reason": "private"}`
- Delete any pre-existing public `MeetingSummaryModel` row (so re-running the pipeline after marking private cleans up)
- Broadcast a "Private meeting — summary skipped" progress event

### Gap 2 — RAG/vector store indexed private transcripts

**Severity:** Medium-High. `vector_svc.embed_segments(meeting_id, seg_dicts, db)` at `meeting_processing_pipeline.py:445` indexed every segment of every meeting. Cross-meeting search ("ask Zero about anything I've discussed") and `/api/meeting-chat/` would surface private content.

**Fix:** Wrapped the embed step in `if is_private:` guard at `meeting_processing_pipeline.py:441-449`. Private meetings now produce zero RAG chunks. Existing private-meeting chunks are NOT retroactively deleted — see Recommendation 1.

---

## Recommendations / follow-up

These are not gaps that block this audit, but they tighten the model further:

1. **Backfill cleanup pass** — if any prior private meeting got its segments embedded under the old (leaky) code path, those rows are still in the vector table. A one-shot script `scripts/scrub_private_vector_chunks.py` that does `DELETE FROM <vector_table> WHERE meeting_id IN (SELECT id FROM meetings WHERE id IN <private_set>)` would scrub residue.

2. **Tests** — `meeting_privacy_service` and the pipeline gates have no unit tests yet. Add `backend/tests/test_meeting_privacy_pipeline.py` that mounts a fake `summary_svc` + fake `vector_svc` and asserts they are NEVER called when `mark_private(meeting_id)` is set.

3. **External-attendee voice prompt** — `consent.decision == "ask"` currently publishes a toast and silently skips. A stronger flow would have Reachy actually ask the user out loud "external attendee on the invite, record?" inside the confirm window. Tracked separately by the existing wake-presence work.

4. **Audit log** — every `mark_private` call should also write to `notification_events` so the user can see retroactively which meetings were marked private and by what source (voice / api / auto-policy). The hooks are already in place in `notification_bus`; just needs the wire-up in `MeetingPrivacyService.mark_private`.

---

## Files touched

- `backend/app/services/meeting_processing_pipeline.py` (2 gates added)

## Files audited (no change required)

- `backend/app/services/meeting_privacy_service.py`
- `backend/app/services/meeting_consent_service.py`
- `backend/app/services/scheduler_service.py` (auto-record + auto-private call sites)
- `backend/app/services/meeting_followup_service.py` (private gate verified)
- `backend/app/services/meeting_vault_writer.py` (private→stub verified via pipeline call)
- `backend/app/routers/meetings.py` (privacy API endpoints)
- `backend/app/services/reachy_realtime/tools.py` (`mark_meeting_private` tool)
