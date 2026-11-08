from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, make_engine
import app.models  # noqa: F401  (register tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_online() -> None:
    settings = get_settings()
    schema = settings.db_schema
    engine = make_engine(settings.database_url, schema)
    with engine.connect() as conn:
        # Schema must exist before alembic creates its version table in it.
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.commit()
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            version_table_schema=schema,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
