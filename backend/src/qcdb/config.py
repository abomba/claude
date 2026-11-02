"""Configuration from environment variables only (never from arguments or files in the repo)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy.engine import URL, make_url


class ConfigError(Exception):
    """Raised when the database configuration is missing or unusable."""


def database_url() -> URL:
    """Build the database URL.

    ``QCDB_DATABASE_URL`` (may omit the password) or the libpq ``PG*`` variables. The password
    may come from ``QCDB_DATABASE_PASSWORD_FILE`` (Docker / Nextflow secrets) or ``PGPASSWORD``.
    """
    raw = os.environ.get("QCDB_DATABASE_URL")
    if raw:
        url = make_url(raw)
        if url.drivername in ("postgresql", "postgres"):
            url = url.set(drivername="postgresql+psycopg")
    else:
        host = os.environ.get("PGHOST")
        if not host:
            raise ConfigError(
                "no database configured: set QCDB_DATABASE_URL or PGHOST/PGUSER/PGDATABASE"
            )
        url = URL.create(
            "postgresql+psycopg",
            username=os.environ.get("PGUSER"),
            host=host,
            port=int(os.environ["PGPORT"]) if os.environ.get("PGPORT") else None,
            database=os.environ.get("PGDATABASE"),
        )
    if url.password is None:
        password_file = os.environ.get("QCDB_DATABASE_PASSWORD_FILE")
        if password_file:
            password = Path(password_file).read_text(encoding="utf-8").strip()
            url = url.set(password=password)
        elif os.environ.get("PGPASSWORD"):
            url = url.set(password=os.environ["PGPASSWORD"])
    return url


def masked(url: URL | str) -> str:
    """Render a URL for logs with the password hidden."""
    if isinstance(url, URL):
        return url.render_as_string(hide_password=True)
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)
