"""Consistent database snapshots wrapped in password-authenticated encryption."""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import settings
from app.services import vault

from app.services.backup_crypto import encrypt_archive, decrypt_archive

MAX_BYTES = 48 * 1024 * 1024


def create_backup(password: str) -> tuple[str, bytes]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="spectergate-backup-") as directory:
        folder = Path(directory)
        if settings.database_url.startswith("sqlite"):
            source = settings.database_path
            if source is None or not source.exists():
                raise RuntimeError("Database file is unavailable.")
            snapshot = folder / "database.sqlite3"
            with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as original, closing(sqlite3.connect(snapshot)) as destination:
                original.backup(destination)
            database_kind = "sqlite"
        elif make_url(settings.database_url).get_backend_name() in {"mysql", "mariadb"}:
            binary = shutil.which("mariadb-dump") or shutil.which("mysqldump")
            if not binary:
                raise RuntimeError("Install mariadb-dump or mysqldump before database backup.")
            url = make_url(settings.database_url)
            snapshot = folder / "database.sql"
            env = os.environ.copy()
            env["MYSQL_PWD"] = url.password or ""
            command = [binary,"--single-transaction","--skip-lock-tables",f"--host={url.host or 'localhost'}",f"--port={url.port or 3306}",f"--user={url.username or ''}",f"--result-file={snapshot}","--",url.database or ""]
            result = subprocess.run(command,env=env,capture_output=True,timeout=120)
            if result.returncode:
                raise RuntimeError("MySQL/MariaDB backup failed; check database connectivity.")
            database_kind = "mysql"
        else:
            binary = shutil.which("pg_dump")
            if not binary:
                raise RuntimeError("Install pg_dump to back up PostgreSQL.")
            url = make_url(settings.database_url)
            snapshot = folder / "database.dump"
            env = os.environ.copy()
            env["PGPASSWORD"] = url.password or ""
            command = [binary, "--format=custom", "--no-owner", "--no-acl", "--file", str(snapshot), "--host", url.host or "localhost", "--port", str(url.port or 5432), "--username", url.username or "", "--dbname", url.database or ""]
            result = subprocess.run(command, env=env, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError("PostgreSQL backup failed; check database connectivity.")
            database_kind = "postgresql"
        archive_bytes = io.BytesIO()
        if snapshot.stat().st_size > 512 * 1024 * 1024:
            raise RuntimeError("Database snapshot is too large for bot delivery; use an offline backup.")
        os.chmod(snapshot, 0o600)
        with tarfile.open(fileobj=archive_bytes, mode="w:gz") as archive:
            archive.add(snapshot, arcname=snapshot.name)
            from app.services.data_restore import export_data
            from app.database import engine
            if database_kind == "sqlite":
                from sqlalchemy import create_engine
                snapshot_engine = create_engine(f"sqlite:///{snapshot.as_posix()}")
                try:
                    with snapshot_engine.connect() as connection:
                        logical = export_data(connection)
                finally:
                    snapshot_engine.dispose()
            else:
                with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                    with connection.begin():
                        logical = export_data(connection)
            portable = tarfile.TarInfo("data.json")
            portable.size, portable.mode = len(logical), 0o600
            archive.addfile(portable, io.BytesIO(logical))
            metadata = json.dumps({"application": "SpecterGate", "version": settings.version, "created_at": stamp, "database": database_kind}).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(metadata), 0o600
            archive.addfile(info, io.BytesIO(metadata))
            if vault.KEY_PATH.exists():
                archive.add(vault.KEY_PATH, arcname="secrets.key")
            config = Path(settings.xray_config_path)
            if config.is_file():
                archive.add(config, arcname="xray/config.json")
        result = encrypt_archive(archive_bytes.getvalue(), password)
        if len(result) > MAX_BYTES:
            raise RuntimeError("Encrypted backup exceeds the supported 48 MiB delivery size.")
        return f"spectergate-{stamp}.sgbackup", result
