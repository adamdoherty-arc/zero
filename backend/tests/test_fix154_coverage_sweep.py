"""Fix-154 — coverage sweep (reflect / index / act-with-approval).

Discriminating tests for the source- AND live-verified fixes shipped by
supervise run fc9c5829. Each asserts the NEW behaviour and fails against the
pre-fix code.

Live baselines captured at fix time (see the sprint retro):
  - weekly review reported "10" stale open tasks when 87 existed
  - 380 of 17,723 vault notes had CRLF frontmatter the regex could not match
  - 1,954 notes / 9,651 headings were mis-detected inside fenced code blocks
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from tests import conftest as _conftest


@pytest.fixture(autouse=True)
async def _db():
    await _conftest._ensure_test_database(_conftest._test_postgres_url())


# ---------------------------------------------------------------------------
# IDX-2 — frontmatter must parse regardless of line endings. A CRLF note used
# to fall through to ({}, full_text), dropping tags/partition AND bypassing the
# constitution's `work` hard-drop (which reads fm["partition"]).
# ---------------------------------------------------------------------------
def test_idx2_crlf_frontmatter_is_parsed():
    from app.services.vault_indexer_service import _parse_frontmatter

    note = "---\r\npartition: work\r\ntags: [a, b]\r\n---\r\n\r\n# Heading\r\nbody text\r\n"
    fm, body = _parse_frontmatter(note)

    assert fm.get("partition") == "work", "CRLF frontmatter must still yield the partition"
    assert fm.get("tags") == ["a", "b"], "CRLF frontmatter must still yield tags"
    assert "partition: work" not in body, "raw YAML must not leak into the indexed body"
    assert "\r" not in body, "body handed to the chunker must be newline-normalized"


def test_idx2_lf_frontmatter_still_parses():
    """Regression guard: the CRLF fix must not disturb the LF path."""
    from app.services.vault_indexer_service import _parse_frontmatter

    fm, body = _parse_frontmatter("---\nid: x\ntags: [z]\n---\n\nbody\n")
    assert fm == {"id": "x", "tags": ["z"]}
    assert body.strip() == "body"


def test_idx2_work_partition_survives_crlf_for_the_hard_drop():
    """The `work` hard-drop keys off fm['partition']; a CRLF note must reach it."""
    from app.services.vault_indexer_service import _parse_frontmatter

    fm, _ = _parse_frontmatter("---\r\npartition: work\r\n---\r\nsecret\r\n")
    assert str(fm.get("partition", "")).strip().lower() == "work", (
        "a CRLF `partition: work` note must be visible to the hard-drop; "
        "pre-fix it parsed as {} and was indexed like any other note"
    )


# ---------------------------------------------------------------------------
# IDX-3 — headings inside fenced code blocks are not headings.
# ---------------------------------------------------------------------------
def test_idx3_headings_inside_code_fence_do_not_split():
    from app.services.vault_indexer_service import _split_by_headings

    text = (
        "# Real Heading\n"
        "intro\n"
        "```bash\n"
        "# Install deps\n"
        "npm install\n"
        "## not a heading either\n"
        "```\n"
        "outro\n"
    )
    sections = _split_by_headings(text)
    paths = {hp for hp, _ in sections}

    assert paths == {"Real Heading"}, f"only the real heading may split; got {paths}"
    body = "\n".join(b for _, b in sections)
    assert "# Install deps" in body, "fenced content must be preserved verbatim"
    assert "## not a heading either" in body


def test_idx3_tilde_fence_also_respected():
    from app.services.vault_indexer_service import _split_by_headings

    sections = _split_by_headings("# H\n~~~\n# fenced\n~~~\ntail\n")
    assert {hp for hp, _ in sections} == {"H"}


def test_idx3_real_headings_after_a_closed_fence_still_split():
    """The fence toggle must not swallow genuine headings that follow it."""
    from app.services.vault_indexer_service import _split_by_headings

    sections = _split_by_headings("# A\n```\n# fenced\n```\n## B\nbody\n")
    paths = {hp for hp, _ in sections}
    assert "A" in paths
    assert "A > B" in paths, f"a real heading after a closed fence must split; got {paths}"


# ---------------------------------------------------------------------------
# R-1 — weekly-review section headers must report the TRUE total, not the
# length of an already-LIMITed preview list.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_r1_weekly_review_counts_are_not_capped_by_the_preview_limit():
    from app.services.weekly_review_service import WeeklyReviewService
    from app.infrastructure.database import get_session
    from app.db.models import TaskModel

    tag = uuid.uuid4().hex[:8]
    very_old = datetime.now(timezone.utc) - timedelta(days=400)
    # 14 stale tasks — comfortably above the preview limit of 10.
    ids = [f"tk-{tag}-{i}" for i in range(14)]
    try:
        async with get_session() as s:
            for i, tid in enumerate(ids):
                s.add(TaskModel(
                    id=tid, title=f"STALE-{tag}-{i}", status="backlog",
                    category="general", priority=3, source="test",
                    created_at=very_old + timedelta(seconds=i),
                ))
            await s.commit()

        rendered = await WeeklyReviewService()._render("2026-Wtest", "2026-07-25")

        line = next(
            ln for ln in rendered.splitlines() if ln.startswith("**Stale open tasks")
        )
        # Parse the rendered total out of "**Stale open tasks (>7d):** N ..."
        total = int(line.split("**")[2].strip().split()[0])
        assert total >= 14, (
            f"header must report the true total, not the preview cap; got {line!r}. "
            "Pre-fix this saturated at 10 no matter how large the backlog was."
        )
        assert "showing" in line, "a truncated preview must say so"
    finally:
        async with get_session() as s:
            await s.execute(delete(TaskModel).where(TaskModel.id.in_(ids)))
            await s.commit()


# ---------------------------------------------------------------------------
# R-3 — blocked tasks are surfaced. The module docstring promised blockers
# since the file was written; nothing ever queried them.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_r3_weekly_review_surfaces_blocked_tasks():
    from app.services.weekly_review_service import WeeklyReviewService
    from app.infrastructure.database import get_session
    from app.db.models import TaskModel

    tag = uuid.uuid4().hex[:8]
    tid = f"tk-blocked-{tag}"
    try:
        async with get_session() as s:
            s.add(TaskModel(
                id=tid, title=f"BLOCKED-{tag}", status="blocked",
                category="general", priority=3, source="test",
                created_at=datetime.now(timezone.utc) - timedelta(days=3),
            ))
            await s.commit()

        rendered = await WeeklyReviewService()._render("2026-Wtest", "2026-07-25")
        assert "**Blocked tasks:**" in rendered, "Get Current must have a Blocked section"
        assert f"BLOCKED-{tag}" in rendered, "a blocked task must be listed"
    finally:
        async with get_session() as s:
            await s.execute(delete(TaskModel).where(TaskModel.id == tid))
            await s.commit()


# ---------------------------------------------------------------------------
# ACT-4 — `status=expired` must include pending-but-past-expiry rows, which
# expire_stale() (hourly cron) has not swept yet. Pre-fix such a row appeared
# on NEITHER filtered tab for up to ~59 minutes.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_act4_expired_bucket_includes_unswept_pending_rows():
    from app.services.approval_queue_service import get_approval_queue
    from app.infrastructure.database import get_session
    from app.db.models import AgentApprovalModel

    tag = uuid.uuid4().hex[:8]
    aid = f"ap-{tag}"
    now = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            s.add(AgentApprovalModel(
                id=aid, tool_name=f"t-{tag}", tier="financial",
                summary=f"S-{tag}", arguments={}, requested_by="test",
                status="pending",                      # never swept
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),   # but already past TTL
            ))
            await s.commit()

        svc = get_approval_queue()
        expired_ids = {r.id for r in await svc.list(status="expired", limit=200)}
        pending_ids = {r.id for r in await svc.list(status="pending", limit=200)}

        assert aid in expired_ids, (
            "a pending-but-past-expiry row must appear in the expired bucket; "
            "pre-fix it was on neither tab until the hourly sweep"
        )
        assert aid not in pending_ids, "it must stay out of pending (Fix-123 A2)"
    finally:
        async with get_session() as s:
            await s.execute(delete(AgentApprovalModel).where(AgentApprovalModel.id == aid))
            await s.commit()


@pytest.mark.asyncio
async def test_act4_expired_bucket_still_returns_literally_expired_rows():
    """The derived bucket must not lose rows the sweep already marked."""
    from app.services.approval_queue_service import get_approval_queue
    from app.infrastructure.database import get_session
    from app.db.models import AgentApprovalModel

    tag = uuid.uuid4().hex[:8]
    aid = f"ap-lit-{tag}"
    now = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            s.add(AgentApprovalModel(
                id=aid, tool_name=f"t-{tag}", tier="write_external",
                summary=f"S-{tag}", arguments={}, requested_by="test",
                status="expired", created_at=now - timedelta(hours=3),
                expires_at=now - timedelta(hours=2),
            ))
            await s.commit()

        svc = get_approval_queue()
        ids = {r.id for r in await svc.list(status="expired", limit=200)}
        assert aid in ids
    finally:
        async with get_session() as s:
            await s.execute(delete(AgentApprovalModel).where(AgentApprovalModel.id == aid))
            await s.commit()


# ---------------------------------------------------------------------------
# ACT-3 — a row stranded in "executing" (process died mid-execution) must be
# reaped. Pre-fix nothing could move it: decide() and expire_stale() both
# required status=="pending", so it was a permanent dead end.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_act3_stranded_executing_row_is_reaped():
    from app.services.approval_queue_service import get_approval_queue
    from app.infrastructure.database import get_session
    from app.db.models import AgentApprovalModel

    tag = uuid.uuid4().hex[:8]
    stuck, fresh = f"ap-stuck-{tag}", f"ap-fresh-{tag}"
    now = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            s.add(AgentApprovalModel(
                id=stuck, tool_name=f"t-{tag}", tier="write_external",
                summary=f"S-{tag}", arguments={}, requested_by="test",
                status="executing", created_at=now - timedelta(hours=5),
                decided_at=now - timedelta(hours=4),   # claimed long ago
            ))
            # A freshly-claimed execution must NOT be reaped out from under itself.
            s.add(AgentApprovalModel(
                id=fresh, tool_name=f"t2-{tag}", tier="write_external",
                summary=f"S2-{tag}", arguments={}, requested_by="test",
                status="executing", created_at=now, decided_at=now,
            ))
            await s.commit()

        await get_approval_queue().expire_stale()

        async with get_session() as s:
            stuck_row = await s.get(AgentApprovalModel, stuck)
            fresh_row = await s.get(AgentApprovalModel, fresh)
            assert stuck_row.status == "failed", (
                "an hours-old executing claim must be reaped to a terminal state"
            )
            assert "stranded" in (stuck_row.error or "")
            assert fresh_row.status == "executing", (
                "an in-flight execution must survive the sweep"
            )
    finally:
        async with get_session() as s:
            await s.execute(
                delete(AgentApprovalModel).where(AgentApprovalModel.id.in_((stuck, fresh)))
            )
            await s.commit()


# ---------------------------------------------------------------------------
# CRITIC-3 — the critic's diff budget must never hide a whole file. A bare
# [:12000] prefix showed only 3 of this run's 7 files, and the critic then
# REJECTED for "the implementation is missing" — a false reject caused entirely
# by the harness (observed on review 40).
# ---------------------------------------------------------------------------
def test_critic3_diff_budget_represents_every_file():
    from app.routers.zero_run import _budget_diff

    files = [f"src/mod_{i}.py" for i in range(7)]
    diff = "".join(
        f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n" + ("+line\n" * 900)
        for f in files
    )
    out = _budget_diff(diff, max_chars=12000)

    for f in files:
        assert f"diff --git a/{f}" in out, f"{f} vanished from the budgeted diff"
    assert len(out) <= 12000 * 1.2, "budgeted diff must respect the cap"
    assert "TRUNCATED" in out, "the critic must be told the diff was truncated"
    assert "NOT evidence" in out, (
        "the notice must stop the critic inferring 'not implemented' from absence"
    )


def test_critic3_small_diff_passes_through_untouched():
    from app.routers.zero_run import _budget_diff

    diff = "diff --git a/a.py b/a.py\n+one line\n"
    assert _budget_diff(diff, max_chars=12000) == diff


# ---------------------------------------------------------------------------
# ACT-5 — approval_service.list_all's filter and payload must agree. Pre-fix
# `?status=pending` returned rows whose serialized status read "expired".
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_act5_list_all_pending_excludes_logically_expired():
    from app.services.approval_service import get_approval_service
    from app.infrastructure.database import get_session
    from app.db.models import ApprovalRequestModel

    tag = uuid.uuid4().hex[:8]
    rid = f"ar-{tag}"
    now = datetime.now(timezone.utc)
    try:
        async with get_session() as s:
            s.add(ApprovalRequestModel(
                id=rid, request_type="write_external", title=f"S-{tag}",
                context_data={}, initiated_by="test", status="pending",
                created_at=now - timedelta(hours=2),
                expires_at=now - timedelta(hours=1),
            ))
            await s.commit()

        svc = get_approval_service()
        pending = await svc.list_all(status="pending", limit=200)
        expired = await svc.list_all(status="expired", limit=200)

        assert rid not in {i["id"] for i in pending["items"]}, (
            "list_all(pending) must not return a row that _to_dict labels 'expired' "
            "— pre-fix the filter and the payload disagreed"
        )
        assert rid in {i["id"] for i in expired["items"]}, (
            "the same row must be reachable via the expired bucket"
        )
    finally:
        async with get_session() as s:
            await s.execute(delete(ApprovalRequestModel).where(ApprovalRequestModel.id == rid))
            await s.commit()
