from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str, schema: str) -> Engine:
    # Tables live in their own schema; pg_trgm lives in public.
    url = url.replace("postgresql://", "postgresql+psycopg://", 1).replace(
        "postgres://", "postgresql+psycopg://", 1
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"options": f"-c search_path={schema},public"},
    )


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return make_engine(s.database_url, s.db_schema)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session
