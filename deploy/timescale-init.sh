#!/usr/bin/env bash
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres --dbname spectergate --set=app_password="$SG_APP_PASSWORD" <<'SQL'
CREATE ROLE spectergate LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE spectergate OWNER TO spectergate;
CREATE EXTENSION IF NOT EXISTS timescaledb;
SQL
