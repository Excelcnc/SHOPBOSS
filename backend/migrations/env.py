"""Alembic environment: uses DATABASE_URL from the app settings and the app's models."""
from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (registers tables)
from app.config import get_settings
from app.db import Base

target_metadata = Base.metadata


def run():
    url = get_settings().sqlalchemy_url
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    with create_engine(url).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
