"""add active status to users

Revision ID: 20260826_01
Revises: 20260808_01
Create Date: 2026-08-26 00:10:00
"""

from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260826_01"
down_revision: Union[str, Sequence[str], None] = "20260808_01"
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
    op.execute(f'ALTER TABLE "{schema}".users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE')


def downgrade() -> None:
    schema = _schema()
    op.execute(f'ALTER TABLE "{schema}".users DROP COLUMN IF EXISTS is_active')
