"""Migration configuration. Credentials come only from the server environment."""
from alembic import context
from backend.database.config import database_url, make_engine
from backend.database.models import Base

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get('connection')
    if supplied is not None:
        run(supplied)
    else:
        with make_engine().connect() as connection:
            run(connection)
