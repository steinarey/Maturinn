"""Manage login users from the command line.

    python -m app.users add <username>       # asks for the password
    python -m app.users passwd <username>    # new password; logs out that user's devices
    python -m app.users remove <username>
    python -m app.users list

In Docker: docker compose exec app python -m app.users add steinar
Pass --password-stdin to read the password from stdin instead of prompting.
"""
import argparse
import getpass
import sys

from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import AppUser, UserSession
from app.services import auth as auth_svc


def _password(args) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Again: ") != first:
        sys.exit("Passwords don't match.")
    return first


def _user(session, name: str) -> AppUser:
    user = session.scalar(select(AppUser).where(AppUser.username == auth_svc.normalize_username(name)))
    if not user:
        sys.exit(f"No user {name!r}.")
    return user


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.users", description="Manage Maturinn login users.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("add", "passwd", "remove"):
        p = sub.add_parser(cmd)
        p.add_argument("username")
        if cmd != "remove":
            p.add_argument("--password-stdin", action="store_true")
    sub.add_parser("list")
    args = parser.parse_args(argv)

    with get_sessionmaker()() as session:
        try:
            if args.cmd == "add":
                user = auth_svc.create_user(session, args.username, _password(args))
                print(f"Added {user.username}.")
            elif args.cmd == "passwd":
                user = _user(session, args.username)
                auth_svc.set_password(session, user, _password(args))
                print(f"Password changed for {user.username}; their devices are logged out.")
            elif args.cmd == "remove":
                user = _user(session, args.username)
                session.delete(user)
                print(f"Removed {user.username}.")
            else:
                rows = session.execute(
                    select(AppUser.username, func.count(UserSession.id))
                    .outerjoin(UserSession).group_by(AppUser.id).order_by(AppUser.username)
                ).all()
                for name, n in rows:
                    print(f"{name}\t{n} device(s)")
                if not rows:
                    print("No users. Add one: python -m app.users add <username>")
            session.commit()
        except auth_svc.AuthError as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main()
