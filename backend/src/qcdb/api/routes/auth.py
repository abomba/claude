"""Login, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from qcdb.api.schemas import LoginIn, MeOut
from qcdb.api.security import (
    COOKIE_NAME,
    DB,
    CurrentUser,
    Settings,
    authenticate,
    create_session,
)
from qcdb.db.models import UserSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeOut, summary="Log in (sets an HttpOnly session cookie)")
def login(body: LoginIn, request: Request, response: Response, db: DB) -> MeOut:
    settings: Settings = request.app.state.settings
    with db.begin():
        user = authenticate(db, body.username, body.password, settings)
        if user is None:
            token = None
        else:
            token, csrf = create_session(db, user, settings)
            me = MeOut(
                id=user.id,
                username=user.username,
                role=user.role,  # type: ignore[arg-type]
                csrf_token=csrf,
            )
    if token is None:
        raise HTTPException(401, "invalid username or password")
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
        max_age=settings.session_idle_minutes * 60,
    )
    return me


@router.post("/logout", status_code=204, response_class=Response)
def logout(user: CurrentUser, db: DB) -> Response:
    with db.begin():
        row = db.get(UserSession, user.token_hash)
        if row is not None:
            db.delete(row)
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/api")
    return response


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return MeOut(
        id=user.user_id,
        username=user.username,
        role=user.role,  # type: ignore[arg-type]
        csrf_token=user.csrf_token,
    )
