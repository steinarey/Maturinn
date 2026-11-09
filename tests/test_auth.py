"""Login: everything is behind it except /login, /health and /static."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.models import UserSession
from app.services import auth as auth_svc

PW = "rétt-lykilorð-123"


@pytest.fixture
def auth_on(monkeypatch, session):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    auth_svc.throttle.reset()
    auth_svc.create_user(session, "Steinar", PW, is_admin=True)
    yield
    auth_svc.throttle.reset()


def login(client, username="steinar", password=PW, next="/"):
    return client.post("/login", data={"username": username, "password": password, "next": next},
                       follow_redirects=False)


def test_password_hashing():
    h = auth_svc.hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert auth_svc.verify_password(PW, h)
    assert not auth_svc.verify_password("rangt", h)
    assert not auth_svc.verify_password(PW, "garbage")


def test_create_user_rules(session):
    with pytest.raises(auth_svc.AuthError, match="at least"):
        auth_svc.create_user(session, "a", "short")
    auth_svc.create_user(session, "Anna", PW)
    with pytest.raises(auth_svc.AuthError, match="exists"):
        auth_svc.create_user(session, " anna ", PW)


def test_everything_guarded(auth_on, client):
    for path in ("/", "/recipes/new", "/import", "/ingredients", "/settings", "/photos/x.jpg"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next="), path
    assert client.get("/api/recipes").status_code == 401
    r = client.get("/fragments/ingredient-row", headers={"HX-Request": "true"})
    assert r.status_code == 401 and r.headers["HX-Redirect"].startswith("/login")
    assert client.post("/recipes", data={"title": "x"}, follow_redirects=False).status_code == 303
    # Open:
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_login_flow_and_cookie(auth_on, client, session):
    assert login(client, password="rangt").status_code == 401
    r = login(client, next="/import")
    assert r.status_code == 303 and r.headers["location"] == "/import"
    cookie = r.headers["set-cookie"]
    assert "maturinn_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=34560000" in cookie
    token = r.cookies["maturinn_session"]
    assert session.query(UserSession).one().token_hash != token  # only a hash is stored
    assert client.get("/").status_code == 200
    assert client.get("/login", follow_redirects=False).status_code == 303  # already logged in


def test_open_redirect_blocked(auth_on, client):
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example"):
        assert login(client, next=bad).headers["location"] == "/"


def test_logout_and_revoke(auth_on, client, session):
    login(client)
    r = client.get("/settings")
    assert "steinar" in r.text and "Innskráð tæki" in r.text and "þetta tæki" in r.text
    client.post("/logout")
    assert client.get("/", follow_redirects=False).status_code == 303
    assert session.query(UserSession).count() == 0

    # Revoking another device logs it out.
    from fastapi.testclient import TestClient
    from app.main import app
    login(client)
    other = TestClient(app)
    login(other)
    other_id = max(s.id for s in session.query(UserSession))
    client.post(f"/settings/sessions/{other_id}/revoke")
    assert other.get("/", follow_redirects=False).status_code == 303
    assert client.get("/").status_code == 200


def test_session_touched_and_cookie_reissued(auth_on, client, session):
    login(client)
    sess = session.query(UserSession).one()
    assert "set-cookie" not in client.get("/").headers  # fresh: nothing to renew
    sess.last_seen = datetime.now(timezone.utc) - timedelta(days=200)
    session.flush()
    r = client.get("/")
    assert "maturinn_session=" in r.headers["set-cookie"]
    assert datetime.now(timezone.utc) - sess.last_seen < timedelta(minutes=1)


def test_throttle(auth_on, client):
    for _ in range(10):
        assert login(client, password="rangt").status_code == 401
    r = login(client)  # right password, but blocked
    assert r.status_code == 429 and "Of margar" in r.text


def test_throttle_global_cap():
    t = auth_svc.LoginThrottle(per_ip=10, global_max=5, window=60)
    for i in range(5):
        t.failed(f"10.0.0.{i}", now=100)
    assert t.blocked("10.9.9.9", now=101)
    assert not t.blocked("10.9.9.9", now=200)  # window passed


def test_cli_add_and_list(session, monkeypatch, capsys):
    from app import users

    class Ctx:
        def __call__(self):
            return self
        def __enter__(self):
            return session
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(users, "get_sessionmaker", lambda: Ctx())
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PW + "\n"))
    users.main(["add", "Gunna", "--password-stdin"])
    users.main(["list"])
    out = capsys.readouterr().out
    assert "Added gunna (admin)." in out and "gunna\tadmin\t0 device(s)" in out
    assert auth_svc.authenticate(session, "GUNNA", PW).is_admin


# --- user management ------------------------------------------------------------

def test_admin_adds_user_who_cannot_manage(auth_on, client, session):
    from fastapi.testclient import TestClient
    from app.main import app

    login(client)
    assert 'href="/admin"' in client.get("/settings").text
    r = client.post("/admin/users", data={"username": "Anna", "password": "short"})
    assert r.status_code == 400 and "minnst 10 stafir" in r.text and 'value="Anna"' in r.text
    r = client.post("/admin/users", data={"username": "steinar", "password": PW})
    assert r.status_code == 400 and "þegar til" in r.text
    r = client.post("/admin/users", data={"username": "Anna", "password": PW}, follow_redirects=False)
    assert r.headers["location"] == "/admin?done=added"
    assert "anna" in client.get("/admin?done=added").text

    anna = TestClient(app)
    assert login(anna, "anna").status_code == 303
    assert anna.get("/").status_code == 200
    assert anna.get("/admin").status_code == 403
    assert anna.post("/admin/users", data={"username": "x", "password": PW}).status_code == 403
    settings = anna.get("/settings").text
    assert 'href="/admin"' not in settings and "steinar" not in settings  # only her own devices
    steinar_sess = session.query(UserSession).filter(UserSession.user.has(username="steinar")).one()
    assert anna.post(f"/settings/sessions/{steinar_sess.id}/revoke").status_code == 404


def test_admin_password_toggle_remove(auth_on, client, session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import AppUser

    login(client)
    client.post("/admin/users", data={"username": "anna", "password": PW})
    anna_id = session.query(AppUser).filter_by(username="anna").one().id
    anna = TestClient(app)
    login(anna, "anna")

    # New password logs her out everywhere.
    client.post(f"/admin/users/{anna_id}/password", data={"password": "nýtt-lykilorð-99"})
    assert anna.get("/", follow_redirects=False).status_code == 303
    assert login(anna, "anna", "nýtt-lykilorð-99").status_code == 303

    client.post(f"/admin/users/{anna_id}/admin")
    assert anna.get("/admin").status_code == 200
    client.post(f"/admin/users/{anna_id}/admin")
    assert anna.get("/admin").status_code == 403

    # Can't demote or remove yourself, so there's always an admin.
    me = session.query(AppUser).filter_by(username="steinar").one()
    assert client.post(f"/admin/users/{me.id}/admin").status_code == 400
    assert client.post(f"/admin/users/{me.id}/delete").status_code == 400

    r = client.post(f"/admin/users/{anna_id}/delete", follow_redirects=False)
    assert r.headers["location"] == "/admin?done=removed"
    assert anna.get("/", follow_redirects=False).status_code == 303
    assert session.query(AppUser).filter_by(username="anna").count() == 0


def test_change_own_password(auth_on, client, session):
    from fastapi.testclient import TestClient
    from app.main import app

    login(client)
    other = TestClient(app)
    login(other)
    new = "annað-lykilorð-42"
    r = client.post("/settings/password", data={"current": "rangt", "password": new, "again": new})
    assert "Rangt lykilorð" in r.text
    r = client.post("/settings/password", data={"current": PW, "password": new, "again": "x"},
                    follow_redirects=False)
    assert "pw_mismatch" in r.headers["location"]
    r = client.post("/settings/password", data={"current": PW, "password": new, "again": new},
                    follow_redirects=False)
    assert r.headers["location"] == "/settings?done=password#password"
    assert client.get("/").status_code == 200  # this device stays logged in
    assert other.get("/", follow_redirects=False).status_code == 303  # the other one doesn't
    assert auth_svc.authenticate(session, "steinar", new)
