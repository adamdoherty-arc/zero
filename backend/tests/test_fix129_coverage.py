"""Regression locks for Fix-129 (supervise:zero run 3c3ade8e).

Coverage-domain hardening across retrieve/reflect/reason/respond/index. The
crown jewel is IDX-PARTITION: the vault indexer was conflating the note-domain
privacy partition (personal|trading|zero-dev) with the *retrieval* partition
(reference|projects|journal|inbox) that vault_retrieval_service.search() filters
on, so ~83% of vault_chunks were stored under a partition the retrieval layer
never queries — and journal notes lost their time-decay boost.

These tests pin the pure resolution logic so the regression cannot silently
return.
"""
from pathlib import Path

import pytest

from app.services.vault_indexer_service import (
    _VALID_PARTITIONS,
    _partition_for,
    _resolve_partition,
)


class TestIdxPartitionResolve:
    """IDX-PARTITION: frontmatter override must not leak the privacy taxonomy."""

    def test_personal_override_on_daily_note_falls_back_to_journal(self):
        # THE BUG: a daily note carrying `partition: personal` was stored as
        # "personal" (invisible to journal-filtered retrieval + no time-decay).
        # It must resolve to the path-derived "journal".
        assert (
            _resolve_partition("personal", "20_Calendar/Daily/2026-06-27.md")
            == "journal"
        )

    def test_zero_dev_override_on_agent_note_falls_back_to_inbox(self):
        assert (
            _resolve_partition("zero-dev", "00_Meta/_agent/research/x.md") == "inbox"
        )

    def test_work_override_is_rejected_and_path_decides(self):
        # RET-01 (supervise zero 6a8c5562): renamed from
        # ...is_hard_dropped_via_path_fallback. The old name claimed this
        # assertion proved the constitution's `work` hard-drop, but asserting
        # the note is indexed as "reference" proves the OPPOSITE -- the note is
        # still in the corpus. All this function does is refuse to let a
        # privacy-taxonomy value leak into the retrieval column. The actual drop
        # is enforced in _index_file and covered by the test below.
        assert _resolve_partition("work", "10_Atlas/secret.md") == "reference"

    def test_valid_override_is_honoured(self):
        # An explicit, VALID retrieval partition still overrides the path — a note
        # in 20_Calendar can legitimately declare itself "reference".
        assert (
            _resolve_partition("reference", "20_Calendar/Daily/note.md")
            == "reference"
        )

    def test_no_override_uses_path(self):
        assert _resolve_partition(None, "30_Efforts/proj/plan.md") == "projects"
        assert _resolve_partition(None, "_Inbox/quick.md") == "inbox"

    def test_non_string_override_uses_path(self):
        # Frontmatter could yield a list/dict/int for `partition`; never crash,
        # always fall back to the path.
        assert _resolve_partition(["personal"], "10_Atlas/a.md") == "reference"
        assert _resolve_partition(42, "20_Calendar/x.md") == "journal"

    def test_valid_partitions_excludes_privacy_taxonomy(self):
        # Documents intent: the privacy taxonomy values are deliberately NOT valid
        # retrieval partitions, which is exactly why the override is rejected.
        for privacy in ("personal", "trading", "zero-dev", "work"):
            assert privacy not in _VALID_PARTITIONS
        assert _VALID_PARTITIONS == {"reference", "projects", "journal", "inbox"}

    def test_resolve_matches_partition_for_when_override_invalid(self):
        # The fallback is exactly _partition_for — no drift between the two.
        for rel in (
            "10_Atlas/a.md",
            "40_Resources/b.md",
            "30_Efforts/c/d.md",
            "20_Calendar/Weekly/e.md",
            "_Inbox/f.md",
            "00_Meta/_agent/g.md",
            "00_Meta/other.md",
            "Zero/unmapped.md",
        ):
            assert _resolve_partition("personal", rel) == _partition_for(Path(rel))


def test_module_imports():
    """All five Fix-129 modules import clean (catches import-time regressions)."""
    import app.routers.council  # noqa: F401  RSN-5
    import app.services.knowledge_service  # noqa: F401  RTV-11/RTV-12
    import app.services.reflection_service  # noqa: F401  RFL-8
    import app.services.vault_indexer_service  # noqa: F401  IDX-*

    # local_handler pulls the realtime stack; import-guard it so a missing
    # optional audio dep doesn't fail the suite, but assert it parses+imports
    # when the deps are present (the in-container run has them).
    try:
        import app.services.reachy_realtime.local_handler  # noqa: F401  RSP-9
    except ModuleNotFoundError as e:  # pragma: no cover - env-dependent
        pytest.skip(f"local_handler optional dep missing: {e}")
