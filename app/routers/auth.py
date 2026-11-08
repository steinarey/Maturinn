"""Login, logout, and the dependency that guards every other route."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import UserSession
from app.services import auth as auth_svc
from app.web import templates

router = APIRouter()


class LoginRequired(Exception):
    pass


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def require_user(request: Request, session: Session = Depends(get_session)):
    """Router dependency: the logged-in user, or LoginRequired."""
    request.state.user = None
    if not get_settings().auth_enabled:
        return None
    sess = auth_svc.find_session(session, request.cookies.get(auth_svc.COOKIE))
    if sess is None:
        raise LoginRequired()
    if auth_svc.touch(sess):
        session.commit()
        request.state.reissue_cookie = request.cookies.get(auth_svc.COOKIE)
    request.state.user = sess.user
    request.state.session_id = sess.id
    return sess.user


async def login_required_handler(request: Request, exc: LoginRequired) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "login required"}, status_code=401)
    target = "/login?next=" + quote(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
    if request.headers.get("hx-request"):
        return Response(status_code=401, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(auth_svc.COOKIE, token, max_age=auth_svc.COOKIE_MAX_AGE, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/")


async def reissue_cookie_middleware(request: Request, call_next):
    """Sliding renewal: browsers cap cookies at 400 days, so re-send it as it's used."""
    response = await call_next(request)
    token = getattr(request.state, "reissue_cookie", None)
    if token and auth_svc.COOKIE not in response.headers.get("set-cookie", ""):
        set_session_cookie(request, response, token)
    return response


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def _login_page(request: Request, status: int = 200, **ctx):
    ctx.setdefault("error", None)
    ctx.setdefault("username", "")
    ctx["next"] = _safe_next(ctx.get("next"))
    return templates.TemplateResponse(request, "login.html", ctx, status_code=status)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", session: Session = Depends(get_session)):
    if auth_svc.find_session(session, request.cookies.get(auth_svc.COOKIE)):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _login_page(request, next=next)


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/"),
          session: Session = Depends(get_session)):
    ip = client_ip(request)
    if auth_svc.throttle.blocked(ip):
        return _login_page(request, 429, error="login.throttled", username=username, next=next)
    user = auth_svc.authenticate(session, username, password)
    if user is None:
        auth_svc.throttle.failed(ip)
        return _login_page(request, 401, error="login.failed", username=username, next=next)
    token = auth_svc.start_session(session, user, request.headers.get("user-agent", ""), ip)
    session.commit()
    response = RedirectResponse(_safe_next(next), status_code=303)
    set_session_cookie(request, response, token)
    return response


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    auth_svc.end_session(session, request.cookies.get(auth_svc.COOKIE))
    session.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth_svc.COOKIE, path="/")
    return response


@router.post("/settings/sessions/{session_id}/revoke", dependencies=[Depends(require_user)])
def revoke(session_id: int, session: Session = Depends(get_session)):
    row = session.get(UserSession, session_id)
    if not row:
        raise HTTPException(404)
    session.delete(row)
    session.commit()
    return RedirectResponse("/settings", status_code=303)
