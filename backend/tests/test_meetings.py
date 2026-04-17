"""
Tests for Meeting Intelligence (DailyMemory) endpoints.

Tests CRUD operations, transcript/summary retrieval, search, speakers, and export.
"""

from unittest.mock import patch, AsyncMock, MagicMock


# ============================================================
# Meeting CRUD
# ============================================================

class TestListMeetings:
    async def test_list_meetings_empty(self, client):
        resp = await client.get("/api/meetings/")
        assert resp.status_code == 200
        data = resp.json()
        assert "meetings" in data
        assert "total" in data
        assert isinstance(data["meetings"], list)

    async def test_list_meetings_with_status_filter(self, client):
        resp = await client.get("/api/meetings/?status=completed")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["meetings"], list)

    async def test_list_meetings_pagination(self, client):
        resp = await client.get("/api/meetings/?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["meetings"], list)


class TestCreateMeeting:
    async def test_create_meeting(self, client):
        resp = await client.post("/api/meetings/", json={
            "title": "Test Meeting",
            "start_time": "2025-01-15T09:00:00Z",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Meeting"
        assert data["status"] == "scheduled"
        assert data["id"]
        assert data["created_at"]

    async def test_create_meeting_with_participants(self, client):
        resp = await client.post("/api/meetings/", json={
            "title": "Team Standup",
            "start_time": "2025-01-15T10:00:00Z",
            "participants": ["Alice", "Bob", "Charlie"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["participants"] == ["Alice", "Bob", "Charlie"]

    async def test_create_meeting_with_end_time(self, client):
        resp = await client.post("/api/meetings/", json={
            "title": "Planning Session",
            "start_time": "2025-01-15T14:00:00Z",
            "end_time": "2025-01-15T15:00:00Z",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["end_time"] is not None


class TestGetMeeting:
    async def test_get_meeting(self, client):
        # Create first
        create_resp = await client.post("/api/meetings/", json={
            "title": "Get Test Meeting",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        # Get
        resp = await client.get(f"/api/meetings/{meeting_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == meeting_id
        assert data["title"] == "Get Test Meeting"

    async def test_get_meeting_not_found(self, client):
        resp = await client.get("/api/meetings/nonexistent-id")
        assert resp.status_code == 404


class TestUpdateMeeting:
    async def test_update_meeting_title(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Original Title",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/meetings/{meeting_id}", json={
            "title": "Updated Title",
        })
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    async def test_update_meeting_status(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Status Test",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/meetings/{meeting_id}", json={
            "status": "completed",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    async def test_update_meeting_not_found(self, client):
        resp = await client.patch("/api/meetings/nonexistent-id", json={
            "title": "Fail",
        })
        assert resp.status_code == 404


class TestDeleteMeeting:
    async def test_delete_meeting(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "To Delete",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/meetings/{meeting_id}")
        assert resp.status_code == 204

        # Verify deleted
        get_resp = await client.get(f"/api/meetings/{meeting_id}")
        assert get_resp.status_code == 404

    async def test_delete_meeting_not_found(self, client):
        resp = await client.delete("/api/meetings/nonexistent-id")
        assert resp.status_code == 404


# ============================================================
# Meeting Export
# ============================================================

class TestExportMeeting:
    async def test_export_meeting_markdown(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Export Test Meeting",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.get(f"/api/meetings/{meeting_id}/export")
        assert resp.status_code == 200
        assert "Export Test Meeting" in resp.text

    async def test_export_meeting_not_found(self, client):
        resp = await client.get("/api/meetings/nonexistent-id/export")
        assert resp.status_code == 404


# ============================================================
# Meeting Transcript
# ============================================================

class TestMeetingTranscript:
    async def test_get_transcript_empty(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "No Transcript",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.get(f"/api/meeting-transcriptions/{meeting_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["meeting_id"] == meeting_id
        assert data["segments"] == []
        assert data["total_segments"] == 0


# ============================================================
# Meeting Summary
# ============================================================

class TestMeetingSummary:
    async def test_get_summary_not_found(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "No Summary",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.get(f"/api/meeting-summaries/{meeting_id}")
        assert resp.status_code == 404


# ============================================================
# Meeting Search
# ============================================================

class TestMeetingSearch:
    async def test_search_requires_query(self, client):
        resp = await client.get("/api/meeting-search/")
        assert resp.status_code == 422  # Missing required 'q' param

    async def test_search_empty_results(self, client):
        resp = await client.get("/api/meeting-search/?q=nonexistent-query-xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0
        assert data["query"] == "nonexistent-query-xyz"


# ============================================================
# Meeting Speakers
# ============================================================

class TestMeetingSpeakers:
    async def test_list_speakers_empty(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Speaker Test",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.get(f"/api/meetings/{meeting_id}/speakers")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_speakers(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Speaker Update Test",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        resp = await client.put(f"/api/meetings/{meeting_id}/speakers", json=[
            {"speaker_label": "SPEAKER_00", "display_name": "Alice"},
            {"speaker_label": "SPEAKER_01", "display_name": "Bob"},
        ])
        assert resp.status_code == 200
        speakers = resp.json()
        assert len(speakers) == 2
        assert speakers[0]["display_name"] == "Alice"
        assert speakers[1]["display_name"] == "Bob"

    async def test_update_speakers_replaces_existing(self, client):
        create_resp = await client.post("/api/meetings/", json={
            "title": "Speaker Replace Test",
            "start_time": "2025-01-15T09:00:00Z",
        })
        meeting_id = create_resp.json()["id"]

        # First update
        await client.put(f"/api/meetings/{meeting_id}/speakers", json=[
            {"speaker_label": "SPEAKER_00", "display_name": "Alice"},
        ])

        # Second update replaces all
        resp = await client.put(f"/api/meetings/{meeting_id}/speakers", json=[
            {"speaker_label": "SPEAKER_00", "display_name": "Charlie"},
        ])
        speakers = resp.json()
        assert len(speakers) == 1
        assert speakers[0]["display_name"] == "Charlie"


# ============================================================
# Recording Status
# ============================================================

class TestRecordingStatus:
    async def test_recording_status_not_recording(self, client):
        resp = await client.get("/api/meeting-recordings/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_recording"] is False


# ============================================================
# Meeting Chat
# ============================================================

class TestMeetingChat:
    async def test_chat_endpoint(self, client):
        with patch("app.routers.meeting_chat.get_meeting_rag_service") as mock_rag:
            mock_service = MagicMock()
            mock_service.query = AsyncMock(return_value={
                "answer": "The meeting discussed project timelines.",
                "sources": [
                    {
                        "meeting_id": "m1",
                        "meeting_title": "Sprint Planning",
                        "text": "We need to deliver by March",
                        "speaker": "Alice",
                        "timestamp": 120.5,
                    }
                ],
            })
            mock_rag.return_value = mock_service

            resp = await client.post("/api/meeting-chat/", json={
                "message": "What was discussed?",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "answer" in data
            assert "sources" in data
            assert data["answer"] == "The meeting discussed project timelines."
            assert len(data["sources"]) == 1
            assert data["sources"][0]["meeting_title"] == "Sprint Planning"


# ============================================================
# Full Lifecycle Integration Test
# ============================================================

class TestMeetingLifecycle:
    async def test_create_update_list_delete_lifecycle(self, client):
        # 1. Create
        create_resp = await client.post("/api/meetings/", json={
            "title": "Lifecycle Meeting",
            "start_time": "2025-01-20T10:00:00Z",
            "participants": ["Dev", "PM"],
        })
        assert create_resp.status_code == 201
        meeting = create_resp.json()
        meeting_id = meeting["id"]

        # 2. List and verify it appears
        list_resp = await client.get("/api/meetings/")
        assert list_resp.status_code == 200
        meetings = list_resp.json()["meetings"]
        assert any(m["id"] == meeting_id for m in meetings)

        # 3. Update status
        update_resp = await client.patch(f"/api/meetings/{meeting_id}", json={
            "status": "completed",
        })
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "completed"

        # 4. Filter by status
        filter_resp = await client.get("/api/meetings/?status=completed")
        assert filter_resp.status_code == 200
        assert any(m["id"] == meeting_id for m in filter_resp.json()["meetings"])

        # 5. Add speaker mappings
        speakers_resp = await client.put(f"/api/meetings/{meeting_id}/speakers", json=[
            {"speaker_label": "SPEAKER_00", "display_name": "Dev Lead"},
        ])
        assert speakers_resp.status_code == 200
        assert len(speakers_resp.json()) == 1

        # 6. Export
        export_resp = await client.get(f"/api/meetings/{meeting_id}/export")
        assert export_resp.status_code == 200
        assert "Lifecycle Meeting" in export_resp.text

        # 7. Get transcript (empty)
        transcript_resp = await client.get(f"/api/meeting-transcriptions/{meeting_id}")
        assert transcript_resp.status_code == 200
        assert transcript_resp.json()["total_segments"] == 0

        # 8. Delete
        delete_resp = await client.delete(f"/api/meetings/{meeting_id}")
        assert delete_resp.status_code == 204

        # 9. Verify deleted
        get_resp = await client.get(f"/api/meetings/{meeting_id}")
        assert get_resp.status_code == 404

        # 10. Speakers also deleted (cascade)
        speakers_after = await client.get(f"/api/meetings/{meeting_id}/speakers")
        assert speakers_after.status_code == 200
        assert speakers_after.json() == []
