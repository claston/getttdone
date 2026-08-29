"""add asynchronous conversion batches, jobs and transactional outbox

Revision ID: 20260829_01
Revises: 20260826_02
Create Date: 2026-08-29 12:00:00
"""

from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op

revision: str = "20260829_01"
down_revision: Union[str, Sequence[str], None] = "20260826_02"
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
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".conversion_quota_consumptions (
            identity_type TEXT NOT NULL,
            identity_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            consumed_units INTEGER NOT NULL CHECK (consumed_units > 0),
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (identity_type, identity_id, idempotency_key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".conversion_batches (
            batch_id TEXT PRIMARY KEY,
            identity_type TEXT NOT NULL,
            identity_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            files_count INTEGER NOT NULL CHECK (files_count BETWEEN 1 AND 12),
            status TEXT NOT NULL CHECK (
                status IN ('uploading', 'queued', 'processing', 'completed', 'completed_with_errors', 'failed')
            ),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            UNIQUE (identity_type, identity_id, idempotency_key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".conversion_jobs (
            job_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL REFERENCES "{schema}".conversion_batches(batch_id) ON DELETE CASCADE,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'uploading', 'uploaded', 'submitted', 'queued', 'running', 'retrying',
                    'completed', 'failed', 'expired'
                )
            ),
            document JSONB NOT NULL,
            identity JSONB NOT NULL,
            preflight_result JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            lease_owner TEXT,
            lease_expires_at TIMESTAMPTZ,
            result_analysis_id TEXT,
            result_payload JSONB,
            result_s3_prefix TEXT,
            failure_code TEXT,
            failure_message TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            UNIQUE (batch_id, idempotency_key)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{schema}".conversion_outbox (
            event_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES "{schema}".conversion_jobs(job_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            published_at TIMESTAMPTZ,
            publish_attempts INTEGER NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
            last_error TEXT
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_conversion_batches_owner_created
        ON "{schema}".conversion_batches(identity_type, identity_id, created_at DESC)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_conversion_batches_expires_at
        ON "{schema}".conversion_batches(expires_at)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_conversion_jobs_batch
        ON "{schema}".conversion_jobs(batch_id, created_at)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_conversion_jobs_status_updated
        ON "{schema}".conversion_jobs(status, updated_at)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_conversion_outbox_pending
        ON "{schema}".conversion_outbox(created_at)
        WHERE published_at IS NULL
        """
    )


def downgrade() -> None:
    schema = _schema()
    op.execute(f'DROP TABLE IF EXISTS "{schema}".conversion_outbox')
    op.execute(f'DROP TABLE IF EXISTS "{schema}".conversion_jobs')
    op.execute(f'DROP TABLE IF EXISTS "{schema}".conversion_batches')
    op.execute(f'DROP TABLE IF EXISTS "{schema}".conversion_quota_consumptions')
