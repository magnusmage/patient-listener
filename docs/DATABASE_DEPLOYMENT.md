# Database migration and deployment — 22 October 2026

## What this update adds

The backend now selects SQLite or PostgreSQL from DATABASE_URL. PostgreSQL uses
SQLAlchemy asyncio and asyncpg, with a packaged Alembic migration. A connection
or migration error stops startup instead of silently choosing a different database.
SQLite remains available for local development and the isolated judge demo.

The same store rules cover helper permissions, words, plans, audio blobs, attempts,
consent history, agent request deduplication and nightly credit reservations.
PostgreSQL advisory transaction locks protect write/check sequences across store
instances. Migrations are an explicit operator step, never automatic startup DDL.

The application loads .env from its working directory. PL_ENV_FILE selects another
explicit file; missing explicit files fail clearly. Exported environment variables
win over file values. Secret variable interpolation is disabled. Restart after edits.

## Keep using the current GPU demo

Do not change to PostgreSQL just to install this update. Preserve your existing
pl.db, .env and sibling virtual environment. Stop the server before replacing
source files. From the GPU project directory:

```bash
source ../.venv/bin/activate
python -m pip install -e . --no-deps
python -m pip install 'python-dotenv>=1,<2'
export PL_DB_PATH="$PWD/pl.db"
export VOICE_ENABLED=true
python -m patient_listener.app
```

Keep DATABASE_URL set to a SQLite URL for this path. Existing exported secrets
continue to work. A saved AI switch remains authoritative after restart; this
update does not issue live model calls on its own.

## Move to Managed PostgreSQL

Provision the workbook's Nebius Managed PostgreSQL service and obtain its private
connection details and CA certificate. Cloud provisioning and connectivity have
not yet been verified in this repository. Do not send credentials in chat or commit
them. URL-encode reserved characters in passwords when constructing a URL.

Install the store dependencies in the target environment. Do not reinstall the
voice extra on the working GPU just to add database support:

```bash
python -m pip install -e '.[store]' --no-deps
python -m pip install 'sqlalchemy[asyncio]>=2.1,<2.2' 'asyncpg>=0.31,<0.33' 'alembic>=1.20,<1.21'
```

On an ordinary new API environment use the project's api and store extras with
dependency resolution instead. The explicit command above preserves an existing
working NeMo/PyTorch installation; dependency compatibility still needs checking
against that environment.

Set these in the deployment environment or private .env:

```dotenv
DATABASE_URL=postgresql+asyncpg://USER:URL_ENCODED_PASSWORD@HOST:5432/DB?sslmode=verify-full&sslrootcert=/absolute/path/to/ca.pem
AI_ENABLED=false
NIGHTLY_ENABLED=false
```

Use the provider's hostname and certificate. The adapter translates sslmode and
certificate parameters for asyncpg. No credentials are passed as CLI arguments.
Clear an old SQLite override before starting PostgreSQL:

```bash
unset PL_DB_PATH
python -m patient_listener.tools.database upgrade
```

### Preserve existing development data, if wanted

Before the first PostgreSQL application startup, stop the old server and keep a
backup of its SQLite database. Use a fresh, migrated PostgreSQL database:

```bash
python -m patient_listener.tools.database import-sqlite --source /absolute/path/to/pl.db
```

The importer takes a consistent SQLite backup snapshot, including committed WAL
changes, without modifying the source. It copies application rows and cached audio
in one PostgreSQL transaction and resets generated ID sequences. Unknown tables
or incompatible columns fail. A target containing application rows is refused;
no existing rows are overwritten. An import failure rolls back the target writes.

Active console tokens and agent credentials are deliberately excluded. Reissue
them for the deployed environment. Existing helper identities and links are copied.
The saved AI switch is copied too: switching AI_ENABLED in .env does not override
that persisted setting. Keep nightly scheduling off until ready.

After migration/import, start the application in the configured environment:

```bash
python -m patient_listener.app
```

For PostgreSQL, admin tools use DATABASE_URL: omit --db. For example, after the
patient exists, grant a new therapist token using the established helper ID:

```bash
python -m patient_listener.tools.console_access grant --user sam --name Sam --role therapist --person demo-margaret
```

The CLI displays a new private token once. Agent provisioning similarly omits
--db; keep its separate helper/person-scoped credential. Production also requires
PL_ENV=production, stable SESSION_TOKEN_SECRET, HTTPS/WSS and trusted proxy setup
appropriate to the actual deployment. Do not turn off HTTPS checks to bypass a
misconfigured cloud proxy.

## Verification and remaining boundaries

The local integration suite runs against a disposable PostgreSQL 16 container,
never the user's pl.db or a managed database. PL_TEST_POSTGRES_URL must identify
localhost/127.0.0.1 and database pltest; its tables are truncated by those tests.
Do not use this variable for deployed databases. Tests cover auth/approval, consent,
profiles, two-store persistence, competing nightly reservations, agent deduplication,
rollback, plan/audio storage and SQLite transfer. All inference is fake in tests.

This migration does not finish the cloud architecture. The current synchronous
store facade waits for async driver results; some API handlers can still block
while awaiting database work. The conservative shared writer lock limits write
throughput. Session/device admission is still process-local: keep one application
worker until shared admission is implemented and tested. This is not approval to
scale replicas yet.

Still required: real Managed PostgreSQL TLS/restart checks, CPU/GPU endpoint split,
Serverless Job/saq scheduling, shared session claims, sandboxed Hermes/OpenShell,
Telegram verification and remaining workbook acceptance gates. The development
nightly loop remains an in-process scheduler, not the final cloud job.

TLS reference: https://magicstack.github.io/asyncpg/current/api/index.html
