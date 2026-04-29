"""baseline postgres schema for gettdone

Revision ID: 20260429_01
Revises:
Create Date: 2026-04-29 00:00:00
"""

from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260429_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str:
    raw = (os.getenv("DATABASE_SCHEMA", "public") or "").strip()
    if not raw:
        return "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        raise RuntimeError("DATABASE_SCHEMA must be a valid PostgreSQL schema name.")
    return raw


def upgrade() -> None:
    schema = _schema()
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    op.create_table(
        "users",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_salt", sa.Text(), nullable=False),
        sa.Column("auth_provider", sa.Text(), nullable=False, server_default="local"),
        sa.Column("provider_user_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        schema=schema,
    )

    op.create_table(
        "anonymous_identities",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
        schema=schema,
    )

    op.create_table(
        "usage",
        sa.Column("identity_type", sa.Text(), nullable=False),
        sa.Column("identity_id", sa.Text(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("quota_limit", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("window_started_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("identity_type", "identity_id"),
        schema=schema,
    )

    op.create_table(
        "user_conversions",
        sa.Column("analysis_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("conversion_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("transactions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], [f"{schema}.users.id"]),
        sa.PrimaryKeyConstraint("analysis_id"),
        schema=schema,
    )

    op.create_table(
        "google_oauth_states",
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("next_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("state"),
        schema=schema,
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_provider_user_id
        ON "{schema}".users(provider_user_id)
        WHERE auth_provider = 'google' AND provider_user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    schema = _schema()
    op.drop_table("google_oauth_states", schema=schema)
    op.drop_table("user_conversions", schema=schema)
    op.drop_table("usage", schema=schema)
    op.drop_table("anonymous_identities", schema=schema)
    op.drop_table("users", schema=schema)
