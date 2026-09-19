"""Migrate an isolated test database; never mutate the application's schema."""
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from backend.database.config import database_url, make_engine
from backend.store import Store


def test_store(test):
    if os.getenv('RIPSTER_TEST_POSTGRES') == '1':
        schema = 'ripster_test_' + uuid.uuid4().hex
        admin = make_engine()
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(database_url(), pool_pre_ping=True, hide_parameters=True,
                               connect_args={'options': f'-csearch_path={schema}', 'connect_timeout': 10})
        def cleanup():
            engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
        test.addCleanup(cleanup)
    else:
        # SQLite is an in-memory test adapter only, never an application data backend.
        engine = create_engine('sqlite://', poolclass=StaticPool,
                               connect_args={'check_same_thread': False})
        test.addCleanup(engine.dispose)
    config = AlembicConfig(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
    return Store(engine)
