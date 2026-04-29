from __future__ import annotations

import os
import re
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _normalize_database_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", 1)
    return raw


def _read_database_schema() -> str:
    raw = (os.getenv("DATABASE_SCHEMA", "public") or "").strip()
    if not raw:
        return "public"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        raise RuntimeError("DATABASE_SCHEMA must be a valid PostgreSQL schema name.")
    return raw


def _build_include_object(schema_name: str):
    def include_object(_object, _name, _type_, reflected, _compare_to):
        if not reflected:
            return True
        object_schema = getattr(_object, "schema", None)
        return object_schema in (None, schema_name)

    return include_object


def run_migrations_offline() -> None:
    url = _normalize_database_url(os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url"))
    schema_name = _read_database_schema()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=schema_name,
        include_schemas=True,
        include_object=_build_include_object(schema_name),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if os.getenv("DATABASE_URL"):
        config.set_main_option("sqlalchemy.url", _normalize_database_url(os.environ["DATABASE_URL"]))

    schema_name = _read_database_schema()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
        connection.execute(text(f'SET search_path TO "{schema_name}", public'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema_name,
            include_schemas=True,
            include_object=_build_include_object(schema_name),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
