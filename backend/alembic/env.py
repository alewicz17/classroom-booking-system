import os
from logging.config import fileConfig

from sqlalchemy import create_engine

from alembic import context

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# Migrations are plain SQL (op.execute); SQLAlchemy is only Alembic's connection layer.
# The app uses a plain postgresql:// URL for psycopg, so pick the psycopg 3 driver here.
url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)

with create_engine(url).connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
