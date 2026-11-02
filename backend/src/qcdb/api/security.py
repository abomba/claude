"""Authentication: argon2id passwords, server-side sessions in PostgreSQL, CSRF double submit,
login throttling and role checks. The session cookie is opaque; only its SHA-256 is stored."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from qcdb.db.models import AppUser, UserSession

ROLES = ("admin", "bioinformatician", "viewer")
COOKIE_NAME = "qcdb_session"
CSRF_HEADER = "X-CSRF-Token"
MIN_PASSWORD_LENGTH = 12
_hasher = PasswordHasher()
# Verified against when the username does not exist, so timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class Settings:
    session_idle_minutes: int = 480
    cookie_secure: bool = True
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    @classmethod
    def from_env(cls) -> Settings:
        def env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            return int(raw) if raw else default

        return cls(
            session_idle_minutes=env_int("QCDB_SESSION_IDLE_MINUTES", 480),
            cookie_secure=os.environ.get("QCDB_COOKIE_SECURE", "true").lower() != "false",
            login_max_failures=env_int("QCDB_LOGIN_MAX_FAILURES", 5),
            login_lock_minutes=env_int("QCDB_LOGIN_LOCK_MINUTES", 15),
        )


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must have at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def authenticate(
    session: Session, username: str, password: str, settings: Settings
) -> AppUser | None:
    """Check credentials with throttling. The caller commits."""
    user = session.scalar(select(AppUser).where(AppUser.username == username))
    ok = verify_password(user.password_hash if user else None, password)
    if user is None:
        return None
    current = now()
    if user.locked_until is not None and user.locked_until > current:
        return None
    if not ok or not user.is_active:
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = current + dt.timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
        return None
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = current
    return user


def create_session(session: Session, user: AppUser, settings: Settings) -> tuple[str, str]:
    """Returns (cookie token, CSRF token)."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    current = now()
    session.execute(delete(UserSession).where(UserSession.expires_at < current))
    session.add(
        UserSession(
            token_hash=token_hash(token),
            user_id=user.id,
            csrf_token=csrf,
            created_at=current,
            last_seen_at=current,
            expires_at=current + dt.timedelta(minutes=settings.session_idle_minutes),
        )
    )
    return token, csrf


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    csrf_token: str
    token_hash: str

    @property
    def technical(self) -> bool:
        """May see technical data (paths, raw data, file names) and contact details."""
        return self.role in ("admin", "bioinformatician")

    @property
    def label(self) -> str:
        return self.username


def get_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.sessionmaker
    with factory() as session:
        yield session


DB = Annotated[Session, Depends(get_db)]


def get_principal(request: Request, db: DB) -> Principal:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    settings: Settings = request.app.state.settings
    with db.begin():
        row = db.get(UserSession, token_hash(token))
        current = now()
        if row is None or row.expires_at <= current:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
        user = db.get(AppUser, row.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account disabled")
        if (current - row.last_seen_at).total_seconds() > 60:
            row.last_seen_at = current
            row.expires_at = current + dt.timedelta(minutes=settings.session_idle_minutes)
        principal = Principal(user.id, user.username, user.role, row.csrf_token, row.token_hash)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent, principal.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or invalid CSRF token")
    return principal


CurrentUser = Annotated[Principal, Depends(get_principal)]


def require(*roles: str) -> Callable[[Principal], Principal]:
    allowed = set(roles)

    def dependency(principal: CurrentUser) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return principal

    return dependency


Editor = Annotated[Principal, Depends(require("admin", "bioinformatician"))]
Admin = Annotated[Principal, Depends(require("admin"))]
