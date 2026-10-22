"""Select storage explicitly; never silently fall back from PostgreSQL to SQLite."""
from pathlib import Path
from ..config import Settings
from .sqlite_store import SqliteStore


def open_store(settings: Settings | None = None, *, sqlite_path: str | None = None):
    cfg=settings or Settings()
    url=cfg.database_url
    if url.startswith(('postgresql://','postgresql+asyncpg://','postgres://')):
        if sqlite_path is not None:
            raise ValueError('Unset PL_DB_PATH / --db when using PostgreSQL DATABASE_URL')
        from .postgres_store import PostgresStore
        return PostgresStore(url,ai_enabled=cfg.ai_enabled)
    if not url.startswith(('sqlite:///','sqlite+aiosqlite:///')):
        raise ValueError('DATABASE_URL must select PostgreSQL or SQLite')
    path=sqlite_path if sqlite_path is not None else url.split(':///',1)[1]
    if not path:raise ValueError('SQLite requires a file path or :memory:')
    return SqliteStore(path,check_same_thread=False,ai_enabled=cfg.ai_enabled)


def open_admin_store(sqlite_path: str | None = None):
    cfg=Settings()
    if sqlite_path is not None:
        if not Path(sqlite_path).is_file():raise ValueError('SQLite file does not exist')
    elif cfg.database_url in {'sqlite:///:memory:','sqlite+aiosqlite:///:memory:'}:
        raise ValueError('Choose an existing SQLite --db file or a PostgreSQL DATABASE_URL')
    return open_store(cfg,sqlite_path=sqlite_path)
