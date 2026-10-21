"""Updater preflight backup, always executed as the unprivileged service user."""
import os
from pathlib import Path


def main():
    from app.database import SessionLocal
    from app.services.vault import get_secret
    from app.services.backups import create_backup
    from app.config import BASE_DIR
    with SessionLocal() as db:
        password=get_secret(db,'backup_password')
    if not password:raise RuntimeError('Configure a backup password before enabling updates.')
    name,content=create_backup(password)
    folder=BASE_DIR/'data/update-backups'
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    descriptor=os.open(folder/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as output:output.write(content)
    print('Encrypted pre-update backup created.')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Pre-update backup failed; the installed application was preserved.') from None
