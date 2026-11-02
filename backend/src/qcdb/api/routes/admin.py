"""Users (admin), audit log (admin) and health checks (anonymous)."""

from __future__ import annotations

from typing import Annotated

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from qcdb.api.common import Page, PageParam, PageSizeParam, audit
from qcdb.api.schemas import AuditOut, HealthOut, PasswordIn, UserIn, UserOut, UserPatch
from qcdb.api.security import DB, Admin, hash_password, now
from qcdb.db.migrate import alembic_config
from qcdb.db.models import AppUser, AuditLog, UserSession

router = APIRouter(tags=["administration"])
health_router = APIRouter(tags=["health"])


def _user_out(user: AppUser) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        locked=user.locked_until is not None and user.locked_until > now(),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, admin: Admin) -> list[UserOut]:
    with db.begin():
        return [_user_out(u) for u in db.scalars(select(AppUser).order_by(AppUser.username))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, db: DB, admin: Admin) -> UserOut:
    try:
        with db.begin():
            user = AppUser(
                username=body.username, role=body.role, password_hash=hash_password(body.password)
            )
            db.add(user)
            db.flush()
            audit(
                db,
                admin,
                "create",
                "app_user",
                user.id,
                {"username": body.username, "role": body.role},
            )
            return _user_out(user)
    except IntegrityError:
        raise HTTPException(409, "username already exists") from None


def _user(db: DB, user_id: int) -> AppUser:
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    return user


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Change role or (de)activate; users are never deleted",
)
def patch_user(user_id: int, body: UserPatch, db: DB, admin: Admin) -> UserOut:
    with db.begin():
        user = _user(db, user_id)
        if user.id == admin.user_id and (
            (body.role is not None and body.role != "admin") or body.is_active is False
        ):
            raise HTTPException(409, "you cannot remove your own admin access")
        changes = {}
        for field in ("role", "is_active"):
            value = getattr(body, field)
            if value is not None and getattr(user, field) != value:
                changes[field] = {"old": getattr(user, field), "new": value}
                setattr(user, field, value)
        if changes:
            if "is_active" in changes or "role" in changes:
                db.execute(delete(UserSession).where(UserSession.user_id == user.id))
            audit(db, admin, "update", "app_user", user.id, changes)
        return _user_out(user)


@router.post(
    "/users/{user_id}/password",
    status_code=204,
    response_class=Response,
    summary="Set a new password (ends the user's sessions)",
)
def set_password(user_id: int, body: PasswordIn, db: DB, admin: Admin) -> Response:
    with db.begin():
        user = _user(db, user_id)
        user.password_hash = hash_password(body.password)
        user.failed_logins = 0
        user.locked_until = None
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        audit(db, admin, "password", "app_user", user.id, {"password": "changed"})
    return Response(status_code=204)


@router.get("/audit", response_model=Page[AuditOut], summary="Audit log (newest first)")
def list_audit(
    db: DB,
    admin: Admin,
    page: PageParam = 1,
    page_size: PageSizeParam = 100,
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    entity_id: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[AuditOut]:
    query = select(AuditLog)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    with db.begin():
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()
        items = [AuditOut.model_validate(r) for r in rows]
    return Page[AuditOut](items=items, total=total, page=page, page_size=page_size)


@health_router.get("/health", response_model=HealthOut, summary="Liveness")
def health() -> HealthOut:
    return HealthOut(status="ok")


@health_router.get(
    "/health/ready",
    response_model=HealthOut,
    responses={503: {"model": HealthOut}},
    summary="Database and migrations",
)
def ready(db: DB, response: Response) -> HealthOut:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    try:
        with db.begin():
            db.execute(text("SELECT 1"))
            current = MigrationContext.configure(db.connection()).get_current_revision()
    except SQLAlchemyError:
        response.status_code = 503
        return HealthOut(status="unavailable", database="unreachable")
    if current != head:
        response.status_code = 503
        return HealthOut(
            status="unavailable", database="ok", migration=f"{current} (expected {head})"
        )
    return HealthOut(status="ok", database="ok", migration=current)
