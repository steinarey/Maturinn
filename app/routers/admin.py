"""User management for admins: add users, set passwords, grant admin, remove.

Admins can't demote or remove themselves, so there is always at least one admin."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AppUser, UserSession
from app.routers.auth import require_user
from app.services import auth as auth_svc
from app.web import templates


def require_admin(user: AppUser | None = Depends(require_user)) -> AppUser | None:
    # user is None only when AUTH_ENABLED=false (dev/tests); then everything is open anyway.
    if user is not None and not user.is_admin:
        raise HTTPException(403)
    return user


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

DONE = {"added", "password", "admin_on", "admin_off", "removed"}


def _page(request: Request, session: Session, status: int = 200, **ctx):
    rows = session.execute(
        select(AppUser, func.count(UserSession.id), func.max(UserSession.last_seen))
        .outerjoin(UserSession).group_by(AppUser.id).order_by(AppUser.username)
    ).all()
    done = request.query_params.get("done")
    ctx = {"rows": rows, "error": None, "done": done if done in DONE else None, "username": "",
           "min_password": auth_svc.MIN_PASSWORD, "me": getattr(request.state, "user", None), **ctx}
    return templates.TemplateResponse(request, "admin.html", ctx, status_code=status)


def _done(what: str) -> RedirectResponse:
    return RedirectResponse(f"/admin?done={what}", status_code=303)


def _other_user(session: Session, request: Request, user_id: int) -> AppUser:
    """A user other than the one logged in (you can't remove or demote yourself)."""
    user = session.get(AppUser, user_id)
    if not user:
        raise HTTPException(404)
    me = getattr(request.state, "user", None)
    if me is not None and me.id == user.id:
        raise HTTPException(400, "Not on yourself.")
    return user


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request, session: Session = Depends(get_session)):
    return _page(request, session)


@router.post("/users", response_class=HTMLResponse)
def add_user(request: Request, username: str = Form(""), password: str = Form(""), is_admin: bool = Form(False),
             session: Session = Depends(get_session)):
    try:
        auth_svc.create_user(session, username, password, is_admin=is_admin)
    except auth_svc.AuthError as e:
        session.rollback()
        return _page(request, session, 400, error=e.key, username=username)
    session.commit()
    return _done("added")


@router.post("/users/{user_id}/password", response_class=HTMLResponse)
def set_password(user_id: int, request: Request, password: str = Form(""), session: Session = Depends(get_session)):
    user = session.get(AppUser, user_id)
    if not user:
        raise HTTPException(404)
    me = getattr(request.state, "user", None)
    try:
        auth_svc.set_password(session, user, password,
                              keep_session_id=getattr(request.state, "session_id", None) if me is user else None)
    except auth_svc.AuthError as e:
        session.rollback()
        return _page(request, session, 400, error=e.key)
    session.commit()
    return _done("password")


@router.post("/users/{user_id}/admin")
def toggle_admin(user_id: int, request: Request, session: Session = Depends(get_session)):
    user = _other_user(session, request, user_id)
    user.is_admin = not user.is_admin
    session.commit()
    return _done("admin_on" if user.is_admin else "admin_off")


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, session: Session = Depends(get_session)):
    session.delete(_other_user(session, request, user_id))
    session.commit()
    return _done("removed")
