#!/usr/bin/env bash
# Sourced by install.sh. Credentials stay in shell memory and the protected .env.
setup_database() {
  DATABASE_URL='sqlite:///./data/spectergate.db'
  [[ "$1" == sqlite ]] && return
  local db_kind=$1 db_password
  db_password=$(openssl rand -hex 32)
  if [[ "$db_kind" == mysql || "$db_kind" == mariadb ]]; then
    if [[ "$db_kind" == mariadb ]]; then
      apt-get install -y mariadb-server mariadb-client
      systemctl enable --now mariadb
    else
      apt-get install -y mysql-server mysql-client
      systemctl enable --now mysql
    fi
    if mysql --batch --skip-column-names -e "SELECT 1 FROM mysql.user WHERE User='spectergate' LIMIT 1" | grep -q 1; then
      echo 'Database account spectergate already exists; refusing to change its credentials.' >&2
      exit 1
    fi
    if mysql --batch --skip-column-names -e "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='spectergate'" | grep -q spectergate; then
      echo 'Database spectergate already exists; refusing to overwrite it.' >&2
      exit 1
    fi
    mysql <<SQL
CREATE DATABASE spectergate CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
CREATE USER 'spectergate'@'127.0.0.1' IDENTIFIED BY '$db_password';
GRANT ALL PRIVILEGES ON spectergate.* TO 'spectergate'@'127.0.0.1';
SQL
    DATABASE_URL="mysql+pymysql://spectergate:$db_password@127.0.0.1:3306/spectergate?charset=utf8mb4"
    return
  fi
  apt-get install -y postgresql postgresql-client
  systemctl enable --now postgresql
  if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='spectergate'" | grep -q 1; then
    echo 'PostgreSQL role spectergate already exists; configure the existing installation explicitly.' >&2
    exit 1
  fi
  if [[ "$db_kind" == timescaledb ]]; then
    # Official Timescale package repository; an HTTPS-downloaded key is scoped
    # to this repository instead of adding it to the global apt trust store.
    local distro_id distro_code pg_major
    distro_id=$(. /etc/os-release; printf '%s' "$ID")
    distro_code=$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")
    [[ "$distro_id" =~ ^(debian|ubuntu)$ && "$distro_code" =~ ^[a-z]+$ ]] || exit 1
    apt-get install -y gnupg
    curl --proto '=https' -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor --yes -o /usr/share/keyrings/spectergate-timescale.gpg
    printf 'deb [signed-by=/usr/share/keyrings/spectergate-timescale.gpg] https://packagecloud.io/timescale/timescaledb/%s/ %s main\n' "$distro_id" "$distro_code" > /etc/apt/sources.list.d/spectergate-timescale.list
    apt-get update
    pg_major=$(runuser -u postgres -- psql -tAc 'SHOW server_version_num')
    pg_major=$((pg_major / 10000))
    apt-get install -y "timescaledb-2-postgresql-$pg_major"
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<'SQL'
SELECT format('ALTER SYSTEM SET shared_preload_libraries = %L', CASE WHEN current_setting('shared_preload_libraries') LIKE '%timescaledb%' THEN current_setting('shared_preload_libraries') ELSE concat_ws(',',NULLIF(current_setting('shared_preload_libraries'),''),'timescaledb') END) \gexec
SQL
    systemctl restart postgresql
  fi
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE spectergate LOGIN PASSWORD '$db_password';
CREATE DATABASE spectergate OWNER spectergate;
SQL
  if [[ "$db_kind" == timescaledb ]]; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d spectergate -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
  fi
  DATABASE_URL="postgresql+psycopg://spectergate:$db_password@127.0.0.1:5432/spectergate"
}
