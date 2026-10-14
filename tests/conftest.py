"""Shared fixtures: a dedicated PostgreSQL database for tests.

Not SQLite, because the schema relies on PostgreSQL-specific features (schema `retail`,
IDENTITY, the `updated_at` trigger, ordered INSERT ... RETURNING, TRUNCATE).

- Session start: create database `<PG_DB>_test` (or `PG_TEST_DB`) and run 01_schema.sql.
- After each test: TRUNCATE every table. Rollback will not work because the generators commit
  per transaction (which is also the behavior under test).
- Session end: drop the test database.
- If Postgres is not running (`make up`), DB tests are skipped and unit tests still run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from retail_pulse.oltp.db import settings

SCHEMA_SQL = Path(__file__).parents[1] / "infras" / "postgres" / "init" / "01_schema.sql"
TEST_DB = os.getenv("PG_TEST_DB", f"{settings.db}_test")
ALL_TABLES = (
    "retail.sales_transaction_item, retail.sales_transaction, retail.promotion_product, "
    "retail.promotion, retail.product, retail.employee, retail.store, "
    "retail.category, retail.brand, retail.payment_method"
)


def _connect(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        dbname=dbname,
        autocommit=True,
        connect_timeout=3,
    )


def _drop_test_db(admin: psycopg.Connection) -> None:
    admin.execute(
        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))
    )


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    if settings.db == TEST_DB:
        pytest.exit("PG_TEST_DB is the real database; stopping to avoid data loss", returncode=2)
    try:
        admin = _connect("postgres")
    except psycopg.OperationalError as exc:
        pytest.skip(f"Cannot connect to PostgreSQL ({exc.__class__.__name__}); run `make up`")

    with admin:
        _drop_test_db(admin)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
        with _connect(TEST_DB) as conn:
            conn.execute(SCHEMA_SQL.read_text())  # type: ignore[arg-type]  # trusted SQL file

        engine = create_engine(settings.url.set(database=TEST_DB))
        try:
            yield engine
        finally:
            engine.dispose()
            _drop_test_db(admin)


@pytest.fixture
def session_factory(pg_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Session factory pointing at the test database; tables are cleaned after each test."""
    yield sessionmaker(pg_engine, expire_on_commit=False)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Session for reading/checking data in tests."""
    with session_factory() as session:
        yield session
