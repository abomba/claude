"""Create a database with the fixture data and web users, for the e2e tests and the demo.

    QCDB_DATABASE_URL=postgresql://postgres@localhost/qcdb_demo \
    QCDB_SEED_PASSWORD=... python scripts/seed_fixtures.py [--recreate]

All data is fictional (fixtures/). Users: admin, bioinformatyk, przegladajacy, all with the
password from QCDB_SEED_PASSWORD (never printed).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text

from qcdb.api.security import hash_password
from qcdb.config import database_url
from qcdb.db.engine import make_engine, make_sessionmaker
from qcdb.db.migrate import upgrade
from qcdb.db.models import AppUser, Owner, SampleOrder
from qcdb.dictionary import default_dictionary_path, import_dictionary, import_labels
from qcdb.loader.core import LoadOptions, load_directory

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LABELS = default_dictionary_path().with_name("metric_labels.pl.psv")
USERS = {"admin": "admin", "bioinformatyk": "bioinformatician", "przegladajacy": "viewer"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true", help="drop and create the database")
    args = parser.parse_args()
    password = os.environ.get("QCDB_SEED_PASSWORD", "")
    if len(password) < 12:
        print("set QCDB_SEED_PASSWORD (at least 12 characters)", file=sys.stderr)
        return 2
    url = database_url()
    if args.recreate:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
    upgrade(url)
    engine = make_engine(url)
    sessions = make_sessionmaker(engine)
    with sessions() as s, s.begin():
        import_dictionary(s, default_dictionary_path(), "seed")
        import_labels(s, LABELS, "pl", "seed")
        for username, role in USERS.items():
            s.add(AppUser(username=username, role=role, password_hash=hash_password(password)))
    steps: list[tuple[str, dict[str, Any]]] = [
        ("RUN_2606", {"run_date": dt.date(2026, 6, 30)}),
        ("RUN_2607", {"run_date": dt.date(2026, 7, 7)}),
        ("orders", {}),
        ("metadata", {"metadata": FIXTURES / "metadata" / "metadata.csv"}),
    ]
    for directory, options in steps:
        with sessions() as s:
            report = load_directory(
                s, LoadOptions(directory=FIXTURES / directory, invoked_by="seed", **options)
            )
        print(f"{directory}: exit {report.exit_code}")
        if report.exit_code != 0:
            print("\n".join(report.lines()), file=sys.stderr)
            return report.exit_code
    with sessions() as s, s.begin():  # a fictional owner for the order from the fixtures
        owner = Owner(full_name="Jan Kowalski", email="jan.kowalski@example.org")
        s.add(owner)
        s.flush()
        order = s.scalar(select(SampleOrder).where(SampleOrder.order_code == "ZL/2026/001"))
        if order is not None:
            order.owner_id = owner.id
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
