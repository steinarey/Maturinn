"""Users, passwords and login sessions.

Passwords: scrypt (stdlib), per-user salt. Sessions: a random token in an
HttpOnly cookie; only its SHA-256 is stored, so a database leak doesn't hand
out logins. Sessions never expire on the server; the cookie is re-issued as
it's used (browsers cap cookie lifetime at 400 days).
"""
import hashlib
import hmac
import secrets
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, UserSession

COOKIE = "maturinn_session"
COOKIE_MAX_AGE = 400 * 24 * 3600  # browser maximum
TOUCH_EVERY = timedelta(days=1)  # how often last_seen is updated and the cookie re-issued
MIN_PASSWORD = 10

_N, _R, _P = 2**15, 8, 1


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


# Compared against when the username doesn't exist, so timing doesn't reveal valid usernames.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def normalize_username(name: str) -> str:
    return name.strip().casefold()


def create_user(session: Session, username: str, password: str) -> AppUser:
    username = normalize_username(username)
    if not username:
        raise AuthError("Username is empty.")
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    if session.scalar(select(AppUser).where(AppUser.username == username)):
        raise AuthError(f"User {username!r} already exists.")
    user = AppUser(username=username, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def set_password(session: Session, user: AppUser, password: str, end_sessions: bool = True) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")
    user.password_hash = hash_password(password)
    if end_sessions:
        user.sessions.clear()


def authenticate(session: Session, username: str, password: str) -> AppUser | None:
    user = session.scalar(select(AppUser).where(AppUser.username == normalize_username(username)))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    return user if user and ok else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: AppUser, user_agent: str = "", ip: str = "") -> str:
    """Creates a session and returns the cookie token (shown only here)."""
    token = secrets.token_urlsafe(32)
    session.add(UserSession(user_id=user.id, token_hash=_token_hash(token),
                            user_agent=user_agent[:300], ip=ip[:64]))
    session.flush()
    return token


def find_session(session: Session, token: str | None) -> UserSession | None:
    if not token or len(token) > 100:
        return None
    return session.scalar(select(UserSession).where(UserSession.token_hash == _token_hash(token)))


def touch(sess: UserSession, now: datetime | None = None) -> bool:
    """Update last_seen at most once per TOUCH_EVERY. True if it did (and the cookie should be re-issued)."""
    now = now or datetime.now(timezone.utc)
    if sess.last_seen and now - sess.last_seen < TOUCH_EVERY:
        return False
    sess.last_seen = now
    return True


def end_session(session: Session, token: str | None) -> None:
    sess = find_session(session, token)
    if sess:
        session.delete(sess)


class LoginThrottle:
    """Slows down password guessing. In memory (one app process).

    Per client IP: `per_ip` failures per `window`. Also a global cap, because
    forwarded client IPs can be spoofed when the proxy isn't pinned. Hitting a
    limit only blocks new logins; existing sessions keep working."""

    def __init__(self, per_ip: int = 10, global_max: int = 50, window: float = 15 * 60):
        self.per_ip, self.global_max, self.window = per_ip, global_max, window
        self._by_ip: dict[str, deque] = {}
        self._all: deque = deque()

    def _prune(self, q: deque, now: float) -> None:
        while q and now - q[0] > self.window:
            q.popleft()

    def blocked(self, ip: str, now: float | None = None) -> bool:
        now = now or time.monotonic()
        self._prune(self._all, now)
        q = self._by_ip.get(ip)
        if q is not None:
            self._prune(q, now)
            if not q:
                del self._by_ip[ip]
        return len(self._all) >= self.global_max or (q is not None and len(q) >= self.per_ip)

    def failed(self, ip: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        self._all.append(now)
        self._by_ip.setdefault(ip, deque()).append(now)

    def reset(self) -> None:
        self._by_ip.clear()
        self._all.clear()


throttle = LoginThrottle()
