#!/usr/bin/env bash
# Runs ONCE, only when the official image initializes an empty volume.
set -euo pipefail
export PL_APP_PASSWORD
PL_APP_PASSWORD="$(cat /run/secrets/app_password)"
psql --no-psqlrc --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password PL_APP_PASSWORD
CREATE ROLE patient_listener_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
ALTER DATABASE patient_listener OWNER TO patient_listener_app;
ALTER SCHEMA public OWNER TO patient_listener_app;
SQL
unset PL_APP_PASSWORD
