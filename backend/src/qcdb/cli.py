"""Command line: ``qcdb load`` and ``qcdb import-dictionary``.

Exit codes: 0 success, 1 validation failure, 2 usage error, 3 unreadable input format.
Database credentials come only from the environment (see :mod:`qcdb.config`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from qcdb import __version__
from qcdb.config import ConfigError, database_url, masked
from qcdb.db.engine import make_engine, make_sessionmaker
from qcdb.dictionary import (
    DictionaryFormatError,
    DictionaryImportError,
    import_dictionary,
    import_labels,
)
from qcdb.loader.core import LoadOptions, load_directory

EXIT_OK, EXIT_VALIDATION, EXIT_USAGE, EXIT_UNREADABLE = 0, 1, 2, 3


def _date(value: str) -> dt.date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qcdb", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"qcdb {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    load = sub.add_parser("load", help="load a result directory")
    load.add_argument("directory", type=Path)
    load.add_argument("--run-id", help="run_id for samples without another source")
    load.add_argument("--run-date", type=_date, help="run date, YYYY-MM-DD")
    load.add_argument("--metadata", type=Path, help="metadata CSV/TSV file")
    load.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")

    imp = sub.add_parser("import-dictionary", help="import the metric dictionary")
    imp.add_argument("file", type=Path)
    imp.add_argument(
        "--labels",
        metavar="LANG",
        help="import a 'key|label|description' translation file for LANG (e.g. pl)",
    )

    user = sub.add_parser(
        "create-user",
        help="create or reset a web user (password read from the terminal or stdin)",
    )
    user.add_argument("username")
    user.add_argument("--role", required=True, choices=["admin", "bioinformatician", "viewer"])
    user.add_argument(
        "--reset-password", action="store_true", help="set a new password for an existing user"
    )
    return parser


def _actor() -> str:
    return os.environ.get("QCDB_INVOKED_BY") or getpass.getuser()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        url = database_url()
    except (ConfigError, OSError) as exc:
        print(f"qcdb: {exc}", file=sys.stderr)
        return EXIT_USAGE
    engine = make_engine(url)
    try:
        session = make_sessionmaker(engine)()
        with session:
            if args.command == "load":
                return _load(session, args)
            if args.command == "create-user":
                return _create_user(session, args)
            return _import(session, args)
    except OperationalError as exc:
        print(
            f"qcdb: cannot connect to the database at {masked(url)}: "
            f"{str(exc.orig).splitlines()[0] if exc.orig else exc}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    finally:
        engine.dispose()


def _load(session: Session, args: argparse.Namespace) -> int:
    options = LoadOptions(
        directory=args.directory,
        run_id=args.run_id,
        run_date=args.run_date,
        metadata=args.metadata,
        dry_run=args.dry_run,
        invoked_by=_actor(),
    )
    report = load_directory(session, options)
    stream = sys.stderr if report.usage_error else sys.stdout
    for line in report.lines():
        print(line, file=stream)
    return report.exit_code


def _import(session: Session, args: argparse.Namespace) -> int:
    path: Path = args.file
    if not path.is_file():
        print(f"qcdb: file not found: {path}", file=sys.stderr)
        return EXIT_USAGE
    try:
        with session.begin():
            if args.labels:
                result = import_labels(session, path, args.labels, _actor())
            else:
                result = import_dictionary(session, path, _actor())
    except DictionaryFormatError as exc:
        print(f"qcdb: {path}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    except DictionaryImportError as exc:
        print(f"qcdb: {path}: import rejected, nothing changed:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return EXIT_VALIDATION
    if result.already_imported:
        print(f"{path.name}: already imported, nothing changed")
    else:
        print(
            f"{path.name}: {result.n_entries} entries, {len(result.added)} added, "
            f"{len(result.changed)} changed"
        )
    for warning in result.warnings:
        print(f"WARN {warning}")
    return EXIT_OK


def _read_password() -> str | None:
    if sys.stdin.isatty():
        first = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != first:
            print("qcdb: passwords do not match", file=sys.stderr)
            return None
        return first
    return sys.stdin.readline().rstrip("\n")


def _create_user(session: Session, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from qcdb.api.security import MIN_PASSWORD_LENGTH, hash_password
    from qcdb.db.models import AppUser, AuditLog, UserSession

    password = _read_password()
    if password is None:
        return EXIT_USAGE
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"qcdb: password must have at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr
        )
        return EXIT_USAGE
    with session.begin():
        user = session.scalar(select(AppUser).where(AppUser.username == args.username))
        if user is not None and not args.reset_password:
            print(f"qcdb: user {args.username!r} exists (use --reset-password)", file=sys.stderr)
            return EXIT_USAGE
        if user is None:
            user = AppUser(
                username=args.username, role=args.role, password_hash=hash_password(password)
            )
            session.add(user)
            action = "create"
        else:
            user.password_hash, user.role = hash_password(password), args.role
            user.failed_logins, user.locked_until, user.is_active = 0, None, True
            session.query(UserSession).filter(UserSession.user_id == user.id).delete()
            action = "password"
        session.flush()
        session.add(
            AuditLog(
                actor_label=f"cli:{_actor()}",
                action=action,
                entity_type="app_user",
                entity_id=str(user.id),
                changes={"username": user.username, "role": user.role},
            )
        )
    print(f"user {args.username!r} ({args.role}) {'created' if action == 'create' else 'updated'}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
