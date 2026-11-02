"""Test database setup: real PostgreSQL only.

Set ``QCDB_TEST_DATABASE_URL`` to a server URL with CREATEDB rights (e.g.
``postgresql+psycopg://postgres@127.0.0.1:5432/postgres``). Otherwise testcontainers is used if
installed and Docker is running. A migrated template database with the dictionary is built
once; each test gets its own copy.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from qcdb.db.engine import make_engine, make_sessionmaker
from qcdb.db.migrate import upgrade
from qcdb.dictionary import default_dictionary_path, import_dictionary
from qcdb.loader.core import LoadOptions, LoadReport, load_directory

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _server_url() -> Iterator[URL]:
    raw = os.environ.get("QCDB_TEST_DATABASE_URL")
    if raw:
        url = make_url(raw)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("set QCDB_TEST_DATABASE_URL or install testcontainers (needs Docker)")
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield make_url(pg.get_connection_url())


@pytest.fixture(scope="session")
def server_url() -> Iterator[URL]:
    yield from _server_url()


def _admin(server_url: URL) -> Engine:
    return create_engine(server_url, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def template_db(server_url: URL) -> Iterator[str]:
    name = f"qcdb_tmpl_{uuid.uuid4().hex[:8]}"
    admin = _admin(server_url)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = server_url.set(database=name)
    upgrade(url)
    engine = make_engine(url)
    with make_sessionmaker(engine)() as session, session.begin():
        import_dictionary(session, default_dictionary_path(), "test")
    engine.dispose()
    yield name
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db_url(server_url: URL, template_db: str) -> Iterator[URL]:
    name = f"qcdb_test_{uuid.uuid4().hex[:10]}"
    admin = _admin(server_url)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"'))
    yield server_url.set(database=name)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def empty_db_url(server_url: URL) -> Iterator[URL]:
    """A database with no schema at all (for migration tests)."""
    name = f"qcdb_empty_{uuid.uuid4().hex[:10]}"
    admin = _admin(server_url)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    yield server_url.set(database=name)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def engine(db_url: URL) -> Iterator[Engine]:
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return make_sessionmaker(engine)


Loader = Callable[..., LoadReport]


@pytest.fixture
def load(sessions: sessionmaker[Session]) -> Loader:
    def _load(directory: Path, **options: Any) -> LoadReport:
        with sessions() as session:
            return load_directory(
                session, LoadOptions(directory=directory, invoked_by="test", **options)
            )

    return _load


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A writable copy of the RUN_2606 fixture directory."""
    target = tmp_path / "RUN_2606"
    shutil.copytree(FIXTURES / "RUN_2606", target)
    return target


def snapshot(engine: Engine) -> dict[str, list[str]]:
    """Every row of every table and of the materialized view, as sorted JSON text."""
    with engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "UNION ALL SELECT matviewname FROM pg_matviews WHERE schemaname = 'public'"
                )
            )
        ]
        return {
            t: [
                r[0]
                for r in conn.execute(
                    text(f'SELECT row_to_json(x)::text AS j FROM "{t}" x ORDER BY j')
                )
            ]
            for t in sorted(tables)
        }
