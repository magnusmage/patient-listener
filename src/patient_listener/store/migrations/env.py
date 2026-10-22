"""Alembic uses the same asyncpg/SQLAlchemy stack as the application."""
import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from patient_listener.store.postgres_store import postgres_engine_options


def apply(connection):
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction(): context.run_migrations()


async def online():
    url, args = postgres_engine_options(context.config.attributes['database_url'])
    engine=create_async_engine(url, connect_args=args,
                               poolclass=NullPool,hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(apply)
    finally: await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError('Use the database upgrade command with an actual PostgreSQL connection')
else:
    asyncio.run(online())
