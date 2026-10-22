"""Apply versioned PostgreSQL migrations using DATABASE_URL, never a password in argv."""
import argparse
from pathlib import Path
from ..config import Settings


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['upgrade','current','import-sqlite'])
    parser.add_argument('--source',help='Existing SQLite file for import-sqlite')
    args=parser.parse_args(argv)
    from alembic import command
    from alembic.config import Config
    from ..store.postgres_store import postgres_url
    url=Settings().database_url
    try:postgres_url(url)
    except Exception:parser.error('Set DATABASE_URL to the PostgreSQL connection URL')
    cfg=Config()
    cfg.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'store'/'migrations'))
    cfg.attributes['database_url']=url
    try:
        if args.command=='import-sqlite':
            if not args.source:parser.error('import-sqlite requires --source')
            from ..store.transfer import import_sqlite
            print(import_sqlite(args.source,url))
        elif args.command=='upgrade':command.upgrade(cfg,'head')
        else:command.current(cfg)
    except Exception:
        print('Database operation failed. Check connection, permissions and migration state; credentials were not printed.')
        return 1
    print('Database '+args.command+' completed.')
    return 0


if __name__=='__main__':raise SystemExit(main())
