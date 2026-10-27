# PostgreSQL: repeatable local rehearsal and server cutover

Prepared 27 October 2026. This package does not provision a cloud service, alter the running demo, or prove live PostgreSQL acceptance by itself. Use the existing SQLite deployment until rehearsal and server checks pass.

## What to give the server owner

Commit/share deploy/postgres/, scripts/postgres_deploy.py, the application's existing migrations and database CLI, and this document. Use the same tested source revision locally and on the server. Do NOT send the generated private directory in Git or a public archive. Create fresh database secrets on the server. The API and GPU then receive the same SERVER application connection securely.

- PostgreSQL 16 official Docker image; named persistent pgdata volume.
- Bootstrap listener_admin account is used only by database administration commands.
- patient_listener_app owns the application database/schema but has NO superuser, create-database, create-role or replication privileges. Use this account in DATABASE_URL for migrations and both services.
- Local default is 127.0.0.1:55432, deliberately separate from a typical local 5432 database. A remote bind is rejected by the helper without --tls. This is only one DB Compose project per host; do not initialize new secrets for an existing volume.
- Native PostgreSQL TLS overlay is supplied for remote connections. An HTTPS reverse proxy for the website does NOT secure PostgreSQL traffic.
- This is a single-host demo deployment, not managed high availability. The server owner must arrange disk capacity, restart recovery, monitoring and off-host backup retention.

## 1. Local rehearsal on Linux GPU/CPU

Run from the project directory using the existing Python virtual environment. Docker Engine and modern Compose (v2 or newer) are required. The helper detects both docker compose and standalone docker-compose, including v5; legacy Compose v1 is rejected. The helper init/backup/restore uses stdlib; app-env additionally uses python-dotenv from the API extra. SQLAlchemy/asyncpg/Alembic from the store extra are needed for migrations. Do not reinstall the GPU's torch/NeMo stack.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python scripts/postgres_deploy.py init
python scripts/postgres_deploy.py check
python scripts/postgres_deploy.py up
python scripts/postgres_deploy.py status
```

`init` creates deploy/postgres/private/.env and two different password files without printing passwords. It refuses to overwrite configuration/secrets. `check` validates Compose syntax; `up` starts only PostgreSQL and waits for its container health. Neither starts the app or changes SQLite. On Windows, Docker Desktop must run Linux containers; the actual server instructions below target Linux.

The default image tag is postgres:16-bookworm, which follows PostgreSQL 16 maintenance updates. After a successful server rehearsal record/pin the tested image digest; this tag is not an immutable release lock.

Secrets use file mounts. On Linux the enclosing private directories are mode 0700 and config/application env files are mode 0600. Password files are container-readable inside these protected directories, so the postgres UID can read Compose bind-mounted secrets. Preserve directory protection; do not copy password files into a public directory. On Windows restrict access with filesystem ACLs. Anyone with Docker admin access is a database administrator.

Changing secret files after the volume is initialized does NOT rotate existing PostgreSQL role passwords. Rotate roles deliberately and update both clients; never delete the volume to fix a password mismatch.

## 2. Create a separate application configuration

```bash
python scripts/postgres_deploy.py app-env \
  --source-env .env.split --out .env.pg-rehearsal
```

This preserves existing logical settings and shared signing/service keys, replaces DATABASE_URL with the local application-role URL, and removes PL_DB_PATH. It never overwrites an existing output file. The running .env.split is unchanged. Without --source-env, the helper creates a DATABASE_URL-only file suitable for CLI checks, not a complete split-service deployment.

Unset stale exported selectors in THIS rehearsal terminal; do not print config/secrets:

```bash
unset DATABASE_URL PL_DB_PATH PL_ENV_FILE
PL_ENV_FILE="$PWD/.env.pg-rehearsal" python -m patient_listener.tools.database upgrade
PL_ENV_FILE="$PWD/.env.pg-rehearsal" python -m patient_listener.tools.database current
```

Do not start API/voice or open an application store against this target before importing; app initialization/seeding can populate tables. Migration CLI creates schema without seeding records. If migration fails, stop and inspect the fixed error message; do not substitute SSL disable for a remote database.

## 3. Rehearse a consistent SQLite import

Create a private SQLite snapshot (may be taken while SQLite runs for a rehearsal). For FINAL cutover stop practice, API, voice and any scheduler first, and take a FRESH snapshot so no new writes are missed. Never copy only a live pl.db while ignoring its WAL.

```bash
python - <<'PY'
import os
from pathlib import Path
import sqlite3
source=Path('pl.db')
backup=Path('pl-postgres-source.db')
if not source.is_file() or backup.exists():
    raise SystemExit('Source missing or backup already exists; nothing overwritten.')
fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
os.close(fd)
src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
dst=sqlite3.connect(backup)
try: src.backup(dst)
finally:
    dst.close()
    src.close()
print('Consistent snapshot created:',backup)
PY
PL_ENV_FILE="$PWD/.env.pg-rehearsal" python -m patient_listener.tools.database import-sqlite \
  --source "$PWD/pl-postgres-source.db"
```

The importer refuses nonempty application tables and unknown source tables, uses a transaction, checks the migration revision and resets sequences. Do not retry into a populated target or truncate a real database to make import pass. Rehearse on an isolated database; final import goes into a separate EMPTY migrated server database.

People, helper identities/links, words, profiles, plans, hint audio, attempts/FSRS, consents and supported audit records are copied. Console/agent access tokens, device enrollment credentials/invitations, privacy challenges and session leases are NOT copied. Reissue helper tokens, re-enroll patient browsers and re-provision any required agent access. No patient data or password should enter Git.

The imported DB's saved AI switch may be true, so turn it off before practice tests:

```bash
PL_ENV_FILE="$PWD/.env.pg-rehearsal" python -m patient_listener.tools.switch \
  --ai-enabled false --reason "PostgreSQL migration rehearsal"
```

## 4. Verify data and application reads

```bash
PL_ENV_FILE="$PWD/.env.pg-rehearsal" python - <<'PY'
from patient_listener.store.factory import open_admin_store
store=open_admin_store()
try:
    for pid in ('demo-margaret','demo-joseph','demo-amina'):
        print(pid,'exists:',store.person_exists(pid),
              'words:',len(store.all_words(pid)),
              'attempts:',len(store.attempts_for(pid)))
finally:store.close()
PY
```

Compare with counts from the immutable source snapshot and the import report, not a still-changing live database. Do not claim successful import merely because migrations succeeded. Verify attempts/FSRS due dates, prepared audio, profile values and helper links too.

Optional DESTRUCTIVE integration tests must ONLY use a separately created LOCAL database named pltest. Existing tests refuse other hosts/database names; never set PL_TEST_POSTGRES_URL to patient_listener or a real demo DB. They are skipped by default. The helper supports app-env --database pltest so credentials need not appear on the command line. Migrate that test DB independently before enabling its tests.

## 5. Back up and prove restoration

```bash
python scripts/postgres_deploy.py backup
```

This writes a private binary custom-format dump under deploy/postgres/private/backups/. A failed dump retains only a .partial file, not a completed .dump. Copy completed dumps to encrypted/off-host storage under a defined retention policy; a dump on the same disk is not disaster recovery. Dumps contain sensitive application data and may contain credential hashes if access has been provisioned.

Use the path printed by backup:

```bash
python scripts/postgres_deploy.py restore-test \
  --source /absolute/path/to/completed.dump \
  --database patient_listener_restore_demo
```

Restore creates a NEW isolated database owned by the app role. It rejects the live database name, names outside patient_listener_restore[_suffix], invalid dumps and any existing target. It never drops or overwrites the live DB. On failure it retains the isolated target for inspection and does not advertise it as usable.

To inspect restored counts using the administrative socket (not exposing credentials):

```bash
docker compose --project-name patient-listener-db \
  --env-file deploy/postgres/private/.env -f deploy/postgres/compose.yaml \
  exec -T postgres psql -U listener_admin -d patient_listener_restore_demo \
  -c 'SELECT COUNT(*) FROM people;' -c 'SELECT COUNT(*) FROM words;' \
  -c 'SELECT COUNT(*) FROM attempts;' -c 'SELECT version_num FROM alembic_version;'
```

After verification the server owner may remove only the isolated restore-test database deliberately. There is no automatic drop command in this helper. Do not serve the restored rehearsal DB publicly.

## 6. Recreate on the CPU server with TLS

Copy the nonsecret deployment package to the CPU server. Create fresh private secrets with init there. This creates an empty database; migrations create tables, then import the final SQLite snapshot. Do not transfer the local Docker volume or assume copied .env files point to the right server.

Before opening remote access:

1. Choose the DB hostname (for example db.patientlistener.magnusmage.com), resolve it correctly from BOTH backend machines, and obtain a matching server certificate/key and CA chain. Use verified TLS; certificate renewal is an operational responsibility.
2. Keep local defaults until certificates and network rules are ready. In private/.env set PL_PG_BIND to the server's intended interface, PL_PG_PORT to the chosen port, PL_PG_TLS_CERT to an absolute certificate-chain file, and PL_PG_TLS_KEY to its absolute private key. Use the file's existing JSON-quoted value style. Do not export conflicting PL_PG_* variables; the helper rejects mismatches.
3. Make the certificate readable inside the DB container. The private key must satisfy PostgreSQL's key-permission rules: e.g. root-owned mode 0640 with the container postgres group, or postgres-owned mode 0600. Determine the image's actual postgres UID/GID; do not assume host and container IDs match. Keep the key's host directory private. A bare read-only bind mount does not fix file ownership.
4. Use a VPN/private route where possible. If published publicly, allow only the CPU/GPU sources using network-level rules that actually apply to Docker-published ports; do not assume a generic UFW rule covers Docker forwarding. The supplied pg_hba rejects cleartext and remote bootstrap-admin access but allows the application role over TLS, so source restrictions are still required at the firewall/VPN layer.
5. Start/validate with the overlay every time:

```bash
python scripts/postgres_deploy.py --tls check
python scripts/postgres_deploy.py --tls up
python scripts/postgres_deploy.py --tls status
```

Supply --tls for backup/restore commands on this deployment too. Otherwise Compose may warn about orphan state/config; never bring it up without TLS after publishing it.

Generate the SERVER application config privately:

```bash
python scripts/postgres_deploy.py app-env \
  --source-env .env.split --out .env.postgres \
  --host db.patientlistener.magnusmage.com --port 55432 \
  --sslmode verify-full --ca-file /absolute/path/to/ca.crt
```

The hostname/port above are examples. Omit --ca-file only when the certificate chain is trusted by the client's normal trust store. Each backend machine needs a valid LOCAL CA file path if one is specified. Provision the same server app credentials securely to API and voice; do NOT run init on the GPU and accidentally create different DB passwords.

Bootstrap listener_admin credentials must not be used by API or voice. Our app needs ownership of its database/schema to apply migrations, but not PostgreSQL superuser permissions.

## 7. Final cutover and rollback

- Preserve working source revision, stable images, SQLite file/WAL snapshot and private configuration. Do not switch during an active practice session.
- Freeze ALL SQLite writers and take the final snapshot. Migrate the empty server DB, import and compare records.
- Put the SERVER DATABASE_URL in both API/voice configurations, remove PL_DB_PATH from config AND exported variables, preserve matching SESSION_TOKEN_SECRET and VOICE_SERVICE_SECRET, and set actual internal/public voice URLs and frontend origins. Do not pass JSON-quoted dotenv files blindly to docker --env-file; use the application's PL_ENV_FILE loader or correctly injected environment values.
- The run_local_voice_container.sh launcher defaults to the original .env.split/pl.db setup. For a SAME-HOST PostgreSQL rehearsal, PL_VOICE_ENV_FILE=.env.pg-api-test selects the existing alternate config without requiring pl.db. Verify the image has store dependencies first. This launcher uses host networking and loopback: final HTTPS routing and separate-host deployment still require their own configuration. Both service images need the store dependencies and current migrations.
- Reissue helper credentials using PL_ENV_FILE=.env.postgres and OMIT --db. Grant only existing patient IDs, including demo-amina if she was imported. Re-enroll browsers on the final frontend origin.
- Verify therapist login/refresh/sign-out, /api/session/me, cue edit/cache invalidation, plan generation, live waits, voice, saved results, rest/resume, Stop and reconnect. Restart API/voice and check persistence. Restart PostgreSQL during maintenance and verify recovery, then confirm an off-host backup and restore procedure.
- Keep SQLite stopped/read-only after cutover; do not allow both independent databases to accept new practice. If validation fails before new PG writes, restore the original configuration and stable services. Rolling back AFTER PG has accepted new activity requires data reconciliation; simply pointing back to SQLite loses those new changes.
- Never run docker compose down -v or delete a volume as part of routine rollback. The stop helper only stops services and preserves data.

## Verification status

Offline tests cover configuration initialization/non-overwrite, distinct secrets, URL encoding, preserved source/shared settings, rejected remote cleartext, Compose/TLS structure, backup output and isolated restore guards. Actual image startup, role initialization, migrations/import, TLS/network access and restore need a working Docker/PostgreSQL runtime. A healthcheck alone does not prove these steps. Local Windows Docker was unresponsive during package preparation, so live migration acceptance is NOT claimed.

References: https://hub.docker.com/_/postgres and https://docs.docker.com/compose/how-tos/use-secrets/ . Pin the tested image digest and review PostgreSQL TLS/key permissions before server publication.
