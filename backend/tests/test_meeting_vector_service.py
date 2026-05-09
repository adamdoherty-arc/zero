import pytest

from app.services.meeting_vector_service import MeetingVectorService


@pytest.mark.asyncio
async def test_meeting_vector_embedding_uses_shared_client(monkeypatch):
    class FakeClient:
        async def embed(self, text: str):
            assert text == "hello meeting"
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr(
        "app.services.meeting_vector_service.get_llm_client",
        lambda: FakeClient(),
    )

    assert await MeetingVectorService().embed_text("hello meeting") == [0.1, 0.2, 0.3]
