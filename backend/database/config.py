"""Server-only database configuration; never serialize connection URLs."""

import os
from sqlalchemy import URL, create_engine


def database_url():
    value = os.getenv('DATABASE_URL')
    if value:
        if value.startswith('postgresql://'):
            value = value.replace('postgresql://', 'postgresql+psycopg://', 1)
        if not value.startswith('postgresql+psycopg://'):
            raise ValueError('DATABASE_URL must be a PostgreSQL connection URL')
        return value
    required = ['POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB']
    if any(not os.getenv(key) for key in required):
        raise ValueError('Set DATABASE_URL or POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB')
    return URL.create('postgresql+psycopg', username=os.environ['POSTGRES_USER'],
                      password=os.environ['POSTGRES_PASSWORD'], host='postgres', port=5432,
                      database=os.environ['POSTGRES_DB'])


def make_engine(url=None):
    return create_engine(url or database_url(), pool_pre_ping=True,
                         connect_args={'connect_timeout': 10}, hide_parameters=True)
