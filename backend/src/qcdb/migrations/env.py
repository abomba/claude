"""Alembic environment. The database URL comes only from the environment (see qcdb.config)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from qcdb.config import database_url

config = context.config
url = config.attributes.get("url") or database_url()
engine = create_engine(url)
with engine.begin() as connection:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
