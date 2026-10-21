"""Idempotent additive upgrades for databases from earlier panel releases."""
from sqlalchemy import inspect


def upgrade(engine):
    # Identifiers and SQL types are fixed application constants, never input.
    changes = {
        "admins": {"totp_secret": "VARCHAR(64)", "totp_enabled": "BOOLEAN NOT NULL DEFAULT FALSE", "recovery_codes_json": "TEXT"},
        "inbounds": {"data_limit_bytes": "BIGINT", "expire_at": "TIMESTAMP", "reset_interval_days": "INTEGER", "last_reset_at": "TIMESTAMP"},
    }
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(1273949831)")
        tables = set(inspect(connection).get_table_names())
        for table, columns in changes.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    if sql_type == "TIMESTAMP" and engine.dialect.name == "postgresql":
                        sql_type = "TIMESTAMP WITH TIME ZONE"
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}')
