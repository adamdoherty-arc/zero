"""Fix-149 — gmail incremental sync now paginates the History API (capture domain).

Carried lead A5 area. `sync_incremental` called history().list() ONCE and then
advanced new_history_id to the mailbox's latest historyId (returned on every
page). When the delta spanned multiple pages (e.g. after downtime), every
message on pages 2+ was silently dropped and never re-fetched, because the
cursor had already jumped past them. The pagination loop is extracted to
`_fetch_all_history` and walks all pages before returning the cursor.
"""
from __future__ import annotations


class _ListReq:
    def __init__(self, page, calls, **kwargs):
        self._page = page
        calls["tokens"].append(kwargs.get("pageToken"))

    def execute(self):
        return self._page


class _History:
    def __init__(self, pages, calls):
        self._pages = pages
        self._calls = calls

    def list(self, **kwargs):
        page = self._pages[self._calls["n"]]
        self._calls["n"] += 1
        return _ListReq(page, self._calls, **kwargs)


class _Users:
    def __init__(self, pages, calls):
        self._h = _History(pages, calls)

    def history(self):
        return self._h


class _Service:
    def __init__(self, pages, calls):
        self._u = _Users(pages, calls)

    def users(self):
        return self._u


def _make_gmail():
    from app.services.gmail_service import GmailService
    svc = GmailService.__new__(GmailService)

    async def _breaker_call(fn):
        return fn()

    svc._breaker_call = _breaker_call
    return svc


async def test_fetch_all_history_walks_every_page():
    svc = _make_gmail()
    calls = {"n": 0, "tokens": []}
    pages = [
        {"history": [{"messagesAdded": [{"message": {"id": "a"}}]}],
         "nextPageToken": "tok2", "historyId": "100"},
        {"history": [{"messagesAdded": [{"message": {"id": "b"}}]}],
         "historyId": "200"},  # no nextPageToken -> last page
    ]
    histories, new_hid = await svc._fetch_all_history(_Service(pages, calls), "50")

    ids = [ma["message"]["id"] for h in histories for ma in h.get("messagesAdded", [])]
    assert ids == ["a", "b"]                # BOTH pages accumulated (was: only "a")
    assert new_hid == "200"                 # cursor = LAST page's id, not page 1's "100"
    assert calls["tokens"] == [None, "tok2"]  # page 1 no token, page 2 uses nextPageToken


async def test_fetch_all_history_single_page():
    svc = _make_gmail()
    calls = {"n": 0, "tokens": []}
    pages = [{"history": [{"messagesAdded": [{"message": {"id": "x"}}]}], "historyId": "77"}]
    histories, new_hid = await svc._fetch_all_history(_Service(pages, calls), "70")
    assert len(histories) == 1
    assert new_hid == "77"
    assert calls["tokens"] == [None]        # exactly one call, no extra page fetch


async def test_fetch_all_history_empty_delta():
    svc = _make_gmail()
    calls = {"n": 0, "tokens": []}
    pages = [{"historyId": "88"}]           # no "history" key at all
    histories, new_hid = await svc._fetch_all_history(_Service(pages, calls), "88")
    assert histories == []
    assert new_hid == "88"
