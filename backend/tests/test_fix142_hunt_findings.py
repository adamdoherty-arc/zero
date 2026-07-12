"""Fix-142 — content-loop/capture coverage-hunt findings (supervise run e68c9958).

F1  image_source_service._safe_source only caught a narrow exception tuple and
    discover_images gathered without return_exceptions — one AttributeError
    from a malformed provider payload aborted the ENTIRE image discovery.
F2  media_content_service.research_media_title: the per-image try/except was a
    no-op against the real failure (uq_media_image_url fires at the shared
    commit, outside the try) — one duplicate URL rolled back the whole
    research run and flipped research_status to "failed".
F3  meal_promo_hunter_service._upsert_promo: codeless (auto-apply) offers
    skipped the code filter entirely and silently merged into any coded row
    sharing service/source/discount shape.
F4  notification_bus.publish: fire-and-forget asyncio.create_task with no
    strong reference — the persist task could be GC'd mid-write (silent drop,
    persist_fail_total never bumped).
F5  calendar_service.smart_reschedule dropped the all-day `date` field, so
    all-day events fell through to utcnow() with a fabricated ~0-min duration.
F6  Zero sprint proxy had no /start passthrough (create/tasks/move/complete
    only) — covered by route + legion_client.start_sprint smoke below.
"""

import asyncio
import uuid

import pytest

from app.models.calendar import EventDateTime
from app.services.calendar_service import CalendarService
from app.services.media_content_service import MediaContentService
from app.services.notification_bus import NotificationBus


# ---------------------------------------------------------------------------
# F1 — _safe_source must swallow ANY exception (documented contract)
# ---------------------------------------------------------------------------


async def test_safe_source_swallows_unexpected_exception():
    from app.services.image_source_service import ImageSourceService

    svc = ImageSourceService.__new__(ImageSourceService)  # skip heavy __init__

    async def source_boom(*args):
        raise AttributeError("'NoneType' object has no attribute 'get'")

    result = await svc._safe_source(source_boom)
    assert result == []
    assert svc._source_health["source_boom"]["failure"] == 1


async def test_safe_source_counts_success_and_empty():
    from app.services.image_source_service import ImageSourceService

    svc = ImageSourceService.__new__(ImageSourceService)

    async def source_full(*args):
        return [{"url": "https://x/1.jpg"}]

    async def source_empty(*args):
        return []

    assert await svc._safe_source(source_full) == [{"url": "https://x/1.jpg"}]
    assert await svc._safe_source(source_empty) == []
    assert svc._source_health["source_full"]["success"] == 1
    assert svc._source_health["source_empty"]["empty"] == 1


# ---------------------------------------------------------------------------
# F2 — image candidates deduped against stored + intra-batch URLs
# ---------------------------------------------------------------------------


def test_filter_new_images_drops_already_stored_urls():
    images = [{"url": "https://a/1.jpg"}, {"url": "https://a/2.jpg"}]
    fresh = MediaContentService._filter_new_images(images, {"https://a/1.jpg"})
    assert fresh == [{"url": "https://a/2.jpg"}]


def test_filter_new_images_drops_intra_batch_duplicates():
    images = [
        {"url": "https://a/1.jpg", "type": "poster"},
        {"url": "https://a/1.jpg", "type": "backdrop"},
        {"url": "https://a/2.jpg"},
    ]
    fresh = MediaContentService._filter_new_images(images, set())
    assert [i["url"] for i in fresh] == ["https://a/1.jpg", "https://a/2.jpg"]


def test_filter_new_images_skips_missing_url():
    images = [{"width": 100}, {"url": None}, {"url": "https://a/3.jpg"}]
    fresh = MediaContentService._filter_new_images(images, set())
    assert fresh == [{"url": "https://a/3.jpg"}]


# ---------------------------------------------------------------------------
# F3 — codeless promo offers are their own dedup identity (DB integration)
# ---------------------------------------------------------------------------


async def test_codeless_promo_does_not_merge_into_coded_row(client):
    from app.services.meal_promo_hunter_service import MealPromoHunterService

    svc = MealPromoHunterService()
    source = f"test-fix142-{uuid.uuid4().hex[:8]}"
    common = dict(
        service_id=None,
        service_slug="test-slug",
        source=source,
        source_url="https://example.test/promos",
        discount_type="percent",
        discount_value=20.0,
        description="20% off",
    )
    # Coded row inserts fresh.
    assert await svc._upsert_promo(code="SAVE20", **common) is True
    # Codeless offer with the same discount shape must NOT merge into the
    # coded row — it is a distinct identity (matches the insert key).
    assert await svc._upsert_promo(code=None, **common) is True
    # Second codeless sighting merges with the codeless row.
    assert await svc._upsert_promo(code=None, **common) is False
    # Coded sighting still merges with the coded row.
    assert await svc._upsert_promo(code="SAVE20", **common) is False


# ---------------------------------------------------------------------------
# F4 — publish holds a strong ref to the persist task until it finishes
# ---------------------------------------------------------------------------


async def test_publish_holds_strong_ref_to_persist_task():
    bus = NotificationBus()
    release = asyncio.Event()
    persisted = []

    async def fake_persist(event):
        await release.wait()
        persisted.append(event)

    bus._persist = fake_persist
    await bus.publish({"type": "test", "payload": {}})

    assert len(bus._bg_tasks) == 1  # strong ref held while in flight
    release.set()
    await asyncio.gather(*bus._bg_tasks)
    await asyncio.sleep(0)  # let done_callback run
    assert persisted and persisted[0]["type"] == "test"
    assert len(bus._bg_tasks) == 0  # discarded once done


# ---------------------------------------------------------------------------
# F5 — all-day events keep their date through the reschedule payload
# ---------------------------------------------------------------------------


def test_event_dt_payload_allday_preserves_date():
    edt = EventDateTime(date_time=None, date="2026-07-15")
    payload = CalendarService._event_dt_payload(edt)
    assert payload == {"date_time": None, "date": "2026-07-15"}
    # And the parser resolves it to the actual day, not utcnow().
    start = CalendarService._event_start_datetime(None, {"start": payload})
    assert (start.year, start.month, start.day) == (2026, 7, 15)


def test_event_dt_payload_timed_event():
    from datetime import datetime

    edt = EventDateTime(date_time=datetime(2026, 7, 15, 9, 30), date=None)
    payload = CalendarService._event_dt_payload(edt)
    assert payload["date_time"] == "2026-07-15T09:30:00"
    start = CalendarService._event_start_datetime(None, {"start": payload})
    assert (start.hour, start.minute) == (9, 30)


# ---------------------------------------------------------------------------
# F6 — sprint proxy /start route exists and delegates to legion_client
# ---------------------------------------------------------------------------


def test_sprint_router_has_start_route():
    from app.routers.sprints import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert any(p.endswith("/{sprint_id}/start") for p in paths)


def test_legion_client_start_sprint_posts_transition():
    from app.services.legion_client import LegionClient

    assert hasattr(LegionClient, "start_sprint")
