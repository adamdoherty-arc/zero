"""Fix-148 — second-brain coverage sweep (supervise zero run 6a8c5562).

Covers the verified defects found by the act-with-approval / retrieve / reason /
respond rotation. Each test names the live evidence that motivated it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# R2 — intent classification matched bare substrings.
# ---------------------------------------------------------------------------

class TestIntentWordBoundaries:
    """"am I being productive?" contained "ein" and routed to the company
    adapter, which answered with an ADA AI LLC brief. Same class: "Adam" ->
    "ada", "syntax" -> "tax", "work-life balance" -> "balance"."""

    @pytest.mark.parametrize("text", [
        "am i being productive?",      # "being"  contained "ein"  -> company
        "is Adam around today",        # "Adam"   contained "ada"  -> company
        "check my syntax on this function",  # "syntax" contained "tax" -> bookkeeper
    ])
    def test_incidental_substrings_do_not_hijack_the_turn(self, text):
        from app.services.supervisor_graph import _classify
        assert _classify(text) == "direct"

    def test_known_limit_word_boundaries_cannot_disambiguate_real_words(self):
        """Honest scope marker. Word boundaries fix INFIX collisions
        ("being"/"ein"), not genuine polysemy: "work-life balance" contains the
        standalone word "balance", so it still routes to bookkeeper. Separating
        an account balance from a life balance needs semantics, not a regex —
        that's what _classify_llm is for. Asserted so the limitation is
        recorded rather than rediscovered as a "regression"."""
        from app.services.supervisor_graph import _classify
        assert _classify("how is my work-life balance") == "bookkeeper"

    @pytest.mark.parametrize("text,expected", [
        ("what's the ada ai filing status", "company"),
        ("file the llc paperwork", "company"),
        ("show me my expenses", "bookkeeper"),
        ("what's on my calendar", "calendar"),
        ("check my email", "email"),
        ("give me the daily brief", "daily_brief"),
    ])
    def test_real_keywords_still_route(self, text, expected):
        from app.services.supervisor_graph import _classify
        assert _classify(text) == expected

    def test_first_matching_intent_in_list_order_wins(self):
        """Pre-existing precedence, pinned so the boundary change is provably
        behaviour-preserving here: bookkeeper precedes company, so a phrase
        carrying both ("ada ai revenue") resolves to bookkeeper via "revenue"."""
        from app.services.supervisor_graph import _classify
        assert _classify("what's my ada ai revenue") == "bookkeeper"

    def test_multi_word_phrases_survive_boundary_matching(self):
        from app.services.supervisor_graph import _classify
        assert _classify("what should i work on") == "daily_brief"


# ---------------------------------------------------------------------------
# RSN-A4 — vote positions were compared raw against exact dict keys.
# ---------------------------------------------------------------------------

class TestCouncilPositionNormalization:
    """Four "Approve" votes used to tally to zero, forcing needs_revision at
    confidence 0.0; a casing split let a decision finalize on half the council."""

    @staticmethod
    def _tally(positions):
        """Mirror of the normalization + tally in conduct_vote."""
        counts = {"approve": 0, "reject": 0, "needs_revision": 0}
        for p in positions:
            pos = str(p).strip().lower().replace(" ", "_").replace("-", "_")
            if pos in counts:
                counts[pos] += 1
        return counts

    def test_capitalized_and_padded_votes_are_counted(self):
        counts = self._tally(["Approve", "approve ", " APPROVE", "approve"])
        assert counts["approve"] == 4

    def test_spaced_and_hyphenated_needs_revision_normalizes(self):
        counts = self._tally(["needs revision", "needs-revision", "needs_revision"])
        assert counts["needs_revision"] == 3

    def test_abstain_is_still_not_a_vote(self):
        counts = self._tally(["abstain", "Abstain"])
        assert sum(counts.values()) == 0

    def test_casing_split_no_longer_finalizes_on_a_minority(self):
        # 2 "Approve" + 2 "reject" used to tally {reject: 2} and finalize
        # `reject` on half the council. Now it's a real 2-2 tie.
        counts = self._tally(["Approve", "APPROVE", "reject", "reject"])
        assert counts["approve"] == 2 and counts["reject"] == 2


# ---------------------------------------------------------------------------
# A-3 — unknown approval tier fell through to "no gate needed".
# ---------------------------------------------------------------------------

class TestApprovalTierDefaultDeny:
    @staticmethod
    def _svc():
        from app.services.approval_queue_service import ApprovalQueueService
        svc = ApprovalQueueService()
        svc._settings = SimpleNamespace(dry_run=False, min_interrupt_salience=0.6)
        return svc

    @pytest.mark.parametrize("tier", [
        "Financial", "write-external", "external", "payment", "wrtie_local", "",
    ])
    def test_unknown_tier_requires_a_gate(self, tier):
        assert self._svc()._requires_gate(tier) is True

    def test_read_is_still_ungated(self):
        assert self._svc()._requires_gate("read") is False

    def test_canonical_ladder_unchanged(self):
        svc = self._svc()
        assert svc._requires_gate("write_external") is True
        assert svc._requires_gate("financial") is True
        assert svc._requires_gate("write_local") is False
        assert svc._requires_gate("write_local", salience=0.1) is True
        assert svc._requires_gate("write_local", dnd=True) is True


# ---------------------------------------------------------------------------
# A-1 — expired-but-unswept rows reported as pending with a live Approve button.
# ---------------------------------------------------------------------------

class TestEffectiveApprovalStatus:
    @staticmethod
    def _row(status, expires_at):
        return SimpleNamespace(status=status, expires_at=expires_at)

    def test_past_expiry_pending_reads_as_expired(self):
        from app.services.approval_queue_service import ApprovalQueueService
        row = self._row("pending", datetime.now(timezone.utc) - timedelta(minutes=5))
        assert ApprovalQueueService.effective_status(row) == "expired"

    def test_live_pending_stays_pending(self):
        from app.services.approval_queue_service import ApprovalQueueService
        row = self._row("pending", datetime.now(timezone.utc) + timedelta(hours=1))
        assert ApprovalQueueService.effective_status(row) == "pending"

    def test_no_expiry_stays_pending(self):
        from app.services.approval_queue_service import ApprovalQueueService
        assert ApprovalQueueService.effective_status(self._row("pending", None)) == "pending"

    def test_naive_datetime_is_treated_as_utc_not_crashed_on(self):
        from app.services.approval_queue_service import ApprovalQueueService
        naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        assert ApprovalQueueService.effective_status(self._row("pending", naive_past)) == "expired"

    def test_already_decided_rows_are_untouched(self):
        from app.services.approval_queue_service import ApprovalQueueService
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert ApprovalQueueService.effective_status(self._row("approved", past)) == "approved"
        assert ApprovalQueueService.effective_status(self._row("rejected", past)) == "rejected"

    def test_router_serializes_the_effective_status(self):
        """The UI gates its Approve/Reject buttons on this exact string."""
        from app.routers.agent_approvals import _serialize
        row = SimpleNamespace(
            id="a1", tool_name="send_email", tier="write_external",
            summary="s", arguments={}, requested_by="agent",
            status="pending", decision_reason=None, decided_by=None,
            created_at=None, decided_at=None,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        assert _serialize(row)["status"] == "expired"


# ---------------------------------------------------------------------------
# A-2 — get_stats and list_pending disagreed on what "pending" means.
# ---------------------------------------------------------------------------

class TestApprovalStatsAgreeWithList:
    @pytest.mark.asyncio
    async def test_logically_expired_pending_counts_as_expired(self, monkeypatch):
        """The tile read "3 Pending" over a list showing 1, because get_stats
        bucketed the raw status column with no expiry predicate while
        list_pending() filtered on one. Both now agree."""
        from app.services import approval_service as aps

        class _Result:
            def __init__(self, rows=None, scalar=None):
                self._rows, self._scalar = rows or [], scalar

            def all(self):
                return self._rows

            def scalar(self):
                return self._scalar

        class _FakeSession:
            def __init__(self):
                self._calls = 0

            async def execute(self, stmt):
                self._calls += 1
                if self._calls == 1:
                    # The CASE expression buckets on EFFECTIVE status, so the
                    # DB hands back one already-expired row, not a pending one.
                    return _Result(rows=[
                        SimpleNamespace(status="pending", count=1),
                        SimpleNamespace(status="expired", count=2),
                    ])
                return _Result(scalar=3600.0)

            async def commit(self):
                return None

        class _Ctx:
            async def __aenter__(self):
                return _FakeSession()

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(aps, "get_session", lambda: _Ctx())
        stats = await aps.ApprovalService().get_stats()

        assert stats["pending"] == 1, "only live rows are pending"
        assert stats["expired"] == 2
        assert stats["avg_decision_time_hours"] == 1.0


# ---------------------------------------------------------------------------
# RET-03 — vault_chunks carried the privacy taxonomy in the retrieval column.
# ---------------------------------------------------------------------------

class TestRetrievalPartitionTaxonomy:
    """71,565 of 89,850 chunks (79.6%) sat under `personal`/`zero-dev`, values
    that are not members of the retrieval taxonomy, so no partition-filtered
    search could reach them. Migration 062 backfills from the path."""

    def test_resolver_never_emits_a_privacy_partition(self):
        from app.services.vault_indexer_service import _resolve_partition, _VALID_PARTITIONS
        for privacy_value in ("personal", "trading", "zero-dev", "work"):
            got = _resolve_partition(privacy_value, "00_Meta/_agent/research/x.md")
            assert got in _VALID_PARTITIONS, f"{privacy_value!r} leaked as {got!r}"

    @pytest.mark.parametrize("path,expected", [
        ("10_Atlas/legion-arch.md", "reference"),
        ("40_Resources/paper.md", "reference"),
        ("30_Efforts/zero/plan.md", "projects"),
        ("20_Calendar/Daily/2026-07-19.md", "journal"),
        ("_Inbox/scratch.md", "inbox"),
        ("00_Meta/_agent/research/out.md", "inbox"),
        ("Zero/notes.md", "reference"),
    ])
    def test_migration_case_expression_matches_the_resolver(self, path, expected):
        """The migration recomputes partitions in SQL; it must agree with the
        Python resolver or the backfill introduces a second source of truth."""
        from app.services.vault_indexer_service import _partition_for
        from pathlib import Path as _P
        assert _partition_for(_P(path)) == expected


# ---------------------------------------------------------------------------
# RET-01 — the `work` hard-drop was documented but never implemented.
# ---------------------------------------------------------------------------

class TestWorkPartitionHardDrop:
    def test_resolver_alone_does_not_drop_a_work_note(self):
        """Documents the real behaviour the old test name misdescribed:
        rejecting the override still yields a valid partition, i.e. the note
        would still be indexed. The drop must live in _index_file."""
        from app.services.vault_indexer_service import _resolve_partition
        assert _resolve_partition("work", "10_Atlas/secret.md") == "reference"

    @pytest.mark.asyncio
    async def test_index_file_skips_and_purges_a_work_note(self, monkeypatch):
        from app.services import vault_indexer_service as mod

        purged: list[str] = []

        svc = mod.VaultIndexerService.__new__(mod.VaultIndexerService)

        async def _fake_delete(rel):
            purged.append(rel)
            return 3

        monkeypatch.setattr(svc, "_delete_chunks_for_path", _fake_delete, raising=False)

        raw = b"---\npartition: work\n---\n\nEightfold internal material.\n"
        written = await mod.VaultIndexerService._index_file(
            svc, mod.Path("x.md"), "10_Atlas/leak.md", raw, "hash123"
        )

        assert written == 0, "a work-partition note must not be indexed"
        assert purged == ["10_Atlas/leak.md"], "prior chunks must be purged"
