"""Hermetic tests for Fix-104 (supervise adversarial gap batch).

Covers the two HIGH-severity dead email-send paths. Each test is built so it
FAILS on the pre-fix code and PASSES on the fix:

  - email_draft_pool._send previously put draft.body under the kwarg "body",
    but GmailService.send_email takes body_text= -> TypeError every send.
  - digest_email.send previously called gmail.send(...) (no such method ->
    AttributeError, not caught by except TypeError) and the fallback used
    body= -> the daily brief never sent.

No DB / network / real Gmail: a fake gmail records the kwargs it receives.
"""
import asyncio
import time

import pytest


class _FakeGmailSendEmailOnly:
    """Mimics GmailService: only send_email(*, to, subject, body_text, ...).

    No `send` attribute and NO `body` parameter — exactly the real signature
    that the old code tripped over.
    """

    def __init__(self):
        self.calls = []

    async def send_email(self, *, to, subject, body_text, account_id=None,
                         thread_id=None, html=None):
        self.calls.append({
            "to": to, "subject": subject, "body_text": body_text,
            "account_id": account_id, "thread_id": thread_id, "html": html,
        })
        return {"id": "msg-123"}


@pytest.mark.asyncio
async def test_email_pool_send_maps_body_to_body_text(monkeypatch):
    from app.services import gmail_service
    from app.services.email_draft_pool_service import Draft, EmailDraftPool

    fake = _FakeGmailSendEmailOnly()
    monkeypatch.setattr(gmail_service, "get_gmail_service", lambda: fake)

    pool = EmailDraftPool()
    draft = Draft(
        id="d1", account_id="acct-2", thread_id="thread-9",
        to="adam@example.com", subject="Re: hi", body="the real body",
        status="approved", created_at=time.time(), updated_at=time.time(),
    )

    msg_id, err = await pool._send(draft)

    assert err is None, f"send should not error, got {err!r}"
    assert msg_id == "msg-123"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    # The crux of the fix: body landed under body_text, not the dead "body" kwarg.
    assert call["body_text"] == "the real body"
    # And per-account routing + threading were not silently dropped.
    assert call["account_id"] == "acct-2"
    assert call["thread_id"] == "thread-9"


@pytest.mark.asyncio
async def test_digest_send_maps_to_body_text(monkeypatch):
    from app.services import gmail_service
    from app.services.digest_email_service import DigestEmailService

    fake = _FakeGmailSendEmailOnly()  # note: NO `send` attr -> old code AttributeError'd
    monkeypatch.setattr(gmail_service, "get_gmail_service", lambda: fake)

    svc = DigestEmailService()
    res = await svc.send(markdown="# Daily brief\n\nbody text", subject="Brief",
                         to="adam@example.com")

    assert res.get("sent") is True, f"digest should send, got {res!r}"
    assert len(fake.calls) == 1
    assert "Daily brief" in fake.calls[0]["body_text"]
    assert fake.calls[0]["to"] == "adam@example.com"


if __name__ == "__main__":
    asyncio.run(test_email_pool_send_maps_body_to_body_text.__wrapped__(  # type: ignore
        lambda *a, **k: None))
