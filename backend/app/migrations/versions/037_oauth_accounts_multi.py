"""Multi-account OAuth: one row per connected Google identity.

Adds `oauth_accounts` table (schema follows fastapi-users `OAuthAccount` shape, MIT)
plus `account_id` columns on `email_cache` and `calendar_event_cache` so cached
data can be filtered/scoped per account.

Backfills the existing single account from `workspace/email/gmail_tokens.json`
(if present) into a row labeled "personal" + tags all existing cached emails
and events with that account id. Safe to re-run — every step is idempotent.

References:
- fastapi-users OAuthAccount schema: https://github.com/frankie567/fastapi-users
- google-auth credentials JSON round-trip: https://googleapis.dev/python/google-auth/latest/user-guide.html
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg


revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)

    # 1. oauth_accounts table
    if "oauth_accounts" not in existing:
        op.create_table(
            "oauth_accounts",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("provider", sa.String(50), nullable=False, server_default="google"),
            sa.Column("label", sa.String(50), nullable=False),
            sa.Column("email", sa.String(200), nullable=False, index=True),
            sa.Column("credentials", pg.JSONB, nullable=False),
            sa.Column("scopes", pg.ARRAY(sa.Text), server_default="{}"),
            sa.Column("quiet_hours", pg.JSONB, server_default="{}"),
            sa.Column("metadata", pg.JSONB, server_default="{}"),
            sa.Column("is_default", sa.Boolean, server_default=sa.false()),
            sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "idx_oauth_accounts_provider_email",
            "oauth_accounts",
            ["provider", "email"],
            unique=True,
        )

    # 2. account_id column on email_cache
    if "account_id" not in _columns(bind, "email_cache"):
        op.add_column("email_cache", sa.Column("account_id", sa.String(64), nullable=True))
        op.create_index("idx_email_cache_account_id", "email_cache", ["account_id"])

    # 3. account_id column on calendar_event_cache
    if "account_id" not in _columns(bind, "calendar_event_cache"):
        op.add_column("calendar_event_cache", sa.Column("account_id", sa.String(64), nullable=True))
        op.create_index("idx_calendar_event_cache_account_id", "calendar_event_cache", ["account_id"])

    # 4. Backfill: import the legacy single-account token file as the "personal"
    #    account, then tag every existing cached email + event with that id.
    legacy_token_path = Path("/app/workspace/email/gmail_tokens.json")
    if not legacy_token_path.exists():
        legacy_token_path = Path("workspace/email/gmail_tokens.json")

    legacy_email = None
    try:
        sync_row = bind.execute(
            sa.text("SELECT email_address FROM sync_status WHERE service_name = 'gmail'")
        ).fetchone()
        if sync_row:
            legacy_email = sync_row[0]
    except Exception:
        pass

    existing_default = bind.execute(
        sa.text("SELECT id FROM oauth_accounts WHERE provider = 'google' AND label = 'personal'")
    ).fetchone()

    if legacy_token_path.exists() and existing_default is None:
        try:
            tokens = json.loads(legacy_token_path.read_text())
            account_id = uuid.uuid4().hex
            email = legacy_email or tokens.get("client_id") or "primary"
            bind.execute(
                sa.text(
                    """
                    INSERT INTO oauth_accounts
                        (id, provider, label, email, credentials, scopes, is_default)
                    VALUES
                        (:id, 'google', 'personal', :email, :credentials, :scopes, true)
                    ON CONFLICT (provider, email) DO NOTHING
                    """
                ),
                {
                    "id": account_id,
                    "email": email,
                    "credentials": json.dumps(tokens),
                    "scopes": tokens.get("scopes", []),
                },
            )
            # Tag existing rows
            bind.execute(
                sa.text("UPDATE email_cache SET account_id = :aid WHERE account_id IS NULL"),
                {"aid": account_id},
            )
            bind.execute(
                sa.text("UPDATE calendar_event_cache SET account_id = :aid WHERE account_id IS NULL"),
                {"aid": account_id},
            )
        except Exception as e:
            # Backfill is best-effort; log and continue. Operator can manually
            # add the account via /api/oauth/accounts later.
            print(f"oauth_accounts backfill skipped: {e}")


def downgrade() -> None:
    bind = op.get_bind()
    if "account_id" in _columns(bind, "calendar_event_cache"):
        op.drop_index("idx_calendar_event_cache_account_id", table_name="calendar_event_cache")
        op.drop_column("calendar_event_cache", "account_id")
    if "account_id" in _columns(bind, "email_cache"):
        op.drop_index("idx_email_cache_account_id", table_name="email_cache")
        op.drop_column("email_cache", "account_id")
    if "oauth_accounts" in _tables(bind):
        op.drop_index("idx_oauth_accounts_provider_email", table_name="oauth_accounts")
        op.drop_table("oauth_accounts")
