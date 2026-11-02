"""Engine and session factory. JSONB is read and written with exact decimal numbers."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from qcdb.config import database_url
from qcdb.jsonio import dumps_exact, loads_db


def make_engine(url: URL | str | None = None) -> Engine:
    return create_engine(
        url if url is not None else database_url(),
        json_serializer=dumps_exact,
        json_deserializer=loads_db,
        pool_pre_ping=True,
    )


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)
