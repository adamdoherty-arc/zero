"""Partial unique index closing the content-outcome boundary-tick race.

Fix-113b shipped check-then-insert dedup for content_published brain
outcomes. Three schedulers fire concurrently at 4-hour boundary ticks
(AsyncIOScheduler runs due jobs as concurrent coroutines), so a row first
visible exactly at a tick could still be recorded 2-3x once. This index
makes the dedup race-proof at the DB layer.

Scoped STRICTLY to (domain='content', action_type='content_published')
because that surface is once-per-action by design; other domains (e.g.
voice turns via zero_brain pass-through) may legitimately re-record an
action_id and must not be constrained.

Revision ID: 057
Revises: 056
"""

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None

_INDEX = "uq_brain_outcome_content_published_once"


def upgrade() -> None:
    # Defensive de-dup before the unique index lands: keep the earliest row
    # per action_id (id is bo-<uuid>, created_at is the tiebreaker).
    op.execute(
        """
        DELETE FROM brain_outcome_records a
        USING brain_outcome_records b
        WHERE a.domain = 'content'
          AND a.action_type = 'content_published'
          AND a.action_id IS NOT NULL
          AND b.domain = a.domain
          AND b.action_type = a.action_type
          AND b.action_id = a.action_id
          AND (b.created_at < a.created_at
               OR (b.created_at = a.created_at AND b.id < a.id))
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX}
        ON brain_outcome_records (action_id)
        WHERE domain = 'content'
          AND action_type = 'content_published'
          AND action_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
