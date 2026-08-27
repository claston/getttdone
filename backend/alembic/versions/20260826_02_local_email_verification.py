"""add local email verification state and tokens

Revision ID: 20260826_02
Revises: 20260826_01
Create Date: 2026-08-26 14:00:00
"""

from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op

revision: str = "20260826_02"
down_revision: Union[str, Sequence[str], None] = "20260826_01"
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
    op.execute(
        f'ALTER TABLE "{schema}".users '
        "ADD COLUMN IF NOT EXISTS email_verification_status TEXT NOT NULL DEFAULT 'verified'"
    )
    op.execute(f'ALTER TABLE "{schema}".users ADD COLUMN IF NOT EXISTS email_verified_at TEXT')
    op.execute(
        f'UPDATE "{schema}".users '
        "SET email_verified_at = created_at "
        "WHERE email_verification_status = 'verified' AND email_verified_at IS NULL"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_users_email_verification_status'
                  AND conrelid = '"{schema}".users'::regclass
            ) THEN
                ALTER TABLE "{schema}".users
                ADD CONSTRAINT ck_users_email_verification_status
                CHECK (email_verification_status IN ('pending', 'verified'));
            END IF;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".email_verification_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES "{schema}".users(id),
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT,
            invalidated_at TEXT,
            delivery_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (delivery_status IN ('pending', 'sent', 'failed')),
            sent_at TEXT,
            provider_message_id TEXT
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_user_created_at
        ON "{schema}".email_verification_tokens(user_id, created_at DESC)
        """
    )


def downgrade() -> None:
    schema = _schema()
    op.execute(f'DROP TABLE IF EXISTS "{schema}".email_verification_tokens')
    op.execute(
        f'ALTER TABLE "{schema}".users DROP CONSTRAINT IF EXISTS ck_users_email_verification_status'
    )
    op.execute(f'ALTER TABLE "{schema}".users DROP COLUMN IF EXISTS email_verified_at')
    op.execute(f'ALTER TABLE "{schema}".users DROP COLUMN IF EXISTS email_verification_status')
