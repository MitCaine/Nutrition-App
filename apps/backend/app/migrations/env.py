from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.core.database import Base
from app.core.database_identity import database_connect_args
from app import models  # noqa: F401
from app.migrations.schema_authority import build_alembic_metadata
from app.operators.phase5c4_roles import assume_migration_owner

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = build_alembic_metadata(Base.metadata)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args=database_connect_args(settings.database_url),
    )

    with connectable.connect() as connection:
        assume_migration_owner(connection)
        # Role inspection/SET ROLE autobegins a SQLAlchemy transaction.  End that
        # transaction before handing the connection to Alembic so migration DDL
        # retains its existing transactional commit boundary.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
