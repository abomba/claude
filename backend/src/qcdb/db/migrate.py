"""Programmatic access to the Alembic migrations shipped in the package."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL


def alembic_config(url: URL | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "qcdb:migrations")
    if url is not None:
        cfg.attributes["url"] = url
    return cfg


def upgrade(url: URL | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: URL | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)
