"""Backfill vault_chunks.partition onto the retrieval taxonomy.

Zero carries two different, same-named taxonomies:

* the **privacy/domain** taxonomy in a note's frontmatter --
  ``personal | trading | zero-dev`` (``work`` is hard-dropped by the vault
  constitution);
* the **retrieval** taxonomy in ``vault_chunks.partition`` --
  ``reference | projects | journal | inbox``, which
  ``vault_retrieval_service.search()`` filters on and whose ``journal`` value
  alone receives the time-decay boost.

IDX-PARTITION taught ``_resolve_partition()`` to stop letting the frontmatter
override leak into the retrieval column, but it only changed what NEW writes
do. Nothing backfilled the rows already on disk, so the corpus stayed split:

    partition   count   oldest       newest
    personal    71534   2026-06-09   2026-06-18   <- frozen at the fix
    reference   11253   2026-06-09   2026-07-19
    inbox        6586   2026-06-09   2026-07-19
    journal       438   2026-06-17   2026-07-14
    zero-dev       31   2026-06-09   2026-06-17   <- frozen at the fix
    projects        8   2026-06-17   2026-06-17

71,565 of 89,850 chunks (79.6%) sat under a value that is not a member of the
retrieval taxonomy at all, so **no partition-filtered search could ever reach
them**. Unfiltered search still returned them, which is why this stayed
invisible: the failure only shows up on the filtered path.

This migration recomputes the partition from the path for every row that is
off-taxonomy, mirroring ``_partition_for()`` in
``app/services/vault_indexer_service.py`` exactly:

    10_Atlas/, 40_Resources/  -> reference
    30_Efforts/               -> projects
    20_Calendar/              -> journal
    _Inbox/                   -> inbox
    00_Meta/_agent/           -> inbox
    (anything else)           -> reference

Rows already carrying a valid retrieval partition are left untouched, so this
is idempotent and safe to re-run.
"""

from __future__ import annotations

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


# Mirrors _partition_for() in vault_indexer_service.py. Order matters: the
# 00_Meta/_agent test must precede the catch-all.
_BACKFILL_SQL = """
UPDATE vault_chunks
SET partition = CASE
        WHEN path LIKE '10_Atlas/%'    THEN 'reference'
        WHEN path LIKE '40_Resources/%' THEN 'reference'
        WHEN path LIKE '30_Efforts/%'  THEN 'projects'
        WHEN path LIKE '20_Calendar/%' THEN 'journal'
        WHEN path LIKE '_Inbox/%'      THEN 'inbox'
        WHEN path LIKE '00_Meta/_agent/%' THEN 'inbox'
        ELSE 'reference'
    END
WHERE partition IS NULL
   OR partition NOT IN ('reference', 'projects', 'journal', 'inbox')
"""

# `_Inbox` and `00_Meta/_agent` both contain a literal underscore, which is a
# single-character wildcard in LIKE. Escape it so `_Inbox/%` cannot also match
# e.g. `XInbox/`. (Postgres LIKE has no default escape for `_`, so be explicit.)
_BACKFILL_SQL = _BACKFILL_SQL.replace(
    "path LIKE '_Inbox/%'", r"path LIKE '\_Inbox/%'"
).replace(
    "path LIKE '00_Meta/_agent/%'", r"path LIKE '00\_Meta/\_agent/%'"
).replace(
    "path LIKE '10_Atlas/%'", r"path LIKE '10\_Atlas/%'"
).replace(
    "path LIKE '40_Resources/%'", r"path LIKE '40\_Resources/%'"
).replace(
    "path LIKE '30_Efforts/%'", r"path LIKE '30\_Efforts/%'"
).replace(
    "path LIKE '20_Calendar/%'", r"path LIKE '20\_Calendar/%'"
)


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # Deliberately a no-op. The pre-backfill state was a mix of two taxonomies
    # with no record of which rows were which, so it cannot be reconstructed --
    # and restoring it would only re-break partition-filtered retrieval.
    pass
