"""Add conversation memory, feedback, goals tables

Revision ID: 014_add_assistant_intelligence
Revises: 013_meeting_intelligence
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

revision = '014_add_assistant_intelligence'
down_revision = '013_meeting_intelligence'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Conversation sessions
    op.create_table(
        'conversation_sessions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('title', sa.Text()),
        sa.Column('project_id', sa.String(64), index=True),
        sa.Column('channel', sa.String(30), server_default='web'),
        sa.Column('message_count', sa.Integer(), server_default='0'),
        sa.Column('summary', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_active', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('is_archived', sa.Boolean(), server_default='false'),
    )
    op.create_index('ix_sessions_last_active', 'conversation_sessions', ['last_active'])

    # Conversation messages
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(64), sa.ForeignKey('conversation_sessions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # User feedback
    op.create_table(
        'user_feedback',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.String(64), index=True),
        sa.Column('message_id', sa.BigInteger()),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('feedback_type', sa.String(30), server_default='response_quality'),
        sa.Column('comment', sa.Text()),
        sa.Column('context', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Learned preferences
    op.create_table(
        'learned_preferences',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('category', sa.String(50), nullable=False, index=True),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), server_default='0.5'),
        sa.Column('evidence_count', sa.Integer(), server_default='1'),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_pref_cat_key', 'learned_preferences', ['category', 'key'], unique=True)

    # User goals
    op.create_table(
        'user_goals',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('category', sa.String(50), server_default='general', index=True),
        sa.Column('status', sa.String(20), server_default='active', index=True),
        sa.Column('target_date', sa.DateTime(timezone=True)),
        sa.Column('progress_pct', sa.Float(), server_default='0.0'),
        sa.Column('milestones', JSONB(), server_default='[]'),
        sa.Column('metrics', JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )

    # Goal check-ins
    op.create_table(
        'goal_checkins',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('goal_id', sa.String(64), sa.ForeignKey('user_goals.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('progress_delta', sa.Float(), server_default='0.0'),
        sa.Column('note', sa.Text()),
        sa.Column('blockers', JSONB(), server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('goal_checkins')
    op.drop_table('user_goals')
    op.drop_table('learned_preferences')
    op.drop_table('user_feedback')
    op.drop_table('conversation_messages')
    op.drop_table('conversation_sessions')
