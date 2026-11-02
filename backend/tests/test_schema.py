"""Migrations apply and roll back; the ORM models agree with the migrated schema."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import URL

from qcdb.db.engine import make_engine
from qcdb.db.migrate import downgrade, upgrade
from qcdb.db.models import Base


def test_migrations_up_down_up(empty_db_url: URL) -> None:
    upgrade(empty_db_url)
    downgrade(empty_db_url, "base")
    engine = make_engine(empty_db_url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
    upgrade(empty_db_url)


def test_models_match_migration(empty_db_url: URL) -> None:
    upgrade(empty_db_url)
    engine = make_engine(empty_db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    # Indexes are defined only in the migration (named as in the design), so they are skipped.
    relevant = [
        d
        for d in diff
        if not (
            isinstance(d, tuple)
            and (
                d[0] in ("add_index", "remove_index")
                or (d[0] == "remove_table" and d[1].name == "alembic_version")
            )
        )
    ]
    assert relevant == []
