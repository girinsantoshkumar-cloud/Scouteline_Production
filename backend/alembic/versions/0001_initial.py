"""initial schema (users, auth_tokens, searches)

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-14

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_tokens",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])

    op.create_table(
        "searches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=120), nullable=False, server_default="Queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False, server_default="[]"),
        sa.Column("requirements", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False, server_default="{}"),
        sa.Column("candidates", postgresql.JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_searches_user_id", "searches", ["user_id"])
    op.create_index("ix_searches_status", "searches", ["status"])
    op.create_index("ix_searches_created_at", "searches", ["created_at"])
    op.create_index("ix_searches_user_created", "searches", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("searches")
    op.drop_table("auth_tokens")
    op.drop_table("users")
