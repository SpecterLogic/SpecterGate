"""Opt-in real database checks; refuses every database name except sg_verify."""
import os
import shutil
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
import pytest
from app.database import Base
from app.models import Admin,AdminRole,VPNUser,Inbound
from app.migrations import upgrade


def test_real_database_migration_snapshot_and_restoration(monkeypatch,tmp_path):
    url=os.getenv('SG_TEST_DATABASE_URL')
    if not url:pytest.skip('Set SG_TEST_DATABASE_URL for a disposable sg_verify database')
    if make_url(url).database!='sg_verify':pytest.fail('Refusing to modify a database other than sg_verify')
    engine=create_engine(url)
    Base.metadata.drop_all(engine)
    try:
        # Upgrade a legacy table without losing its existing row.
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE vpn_users (id INTEGER PRIMARY KEY)')
            connection.exec_driver_sql('INSERT INTO vpn_users(id) VALUES (7)')
        upgrade(engine);upgrade(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT id FROM vpn_users').scalar()==7
            assert {'hwid_limit','renewal_remaining','traffic_reset_days'} <= {c['name'] for c in inspect(connection).get_columns('vpn_users')}
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        if os.getenv('SG_TEST_TIMESCALE')=='1':
            with engine.begin() as connection:connection.execute(text('CREATE EXTENSION IF NOT EXISTS timescaledb'))
        with Session(engine) as db:
            owner=Admin(username='db-owner',password_hash='test-only-hash',role=AdminRole.superadmin,is_owner=True)
            db.add(owner);db.flush()
            user=VPNUser(username='portable-user',created_by=owner.id,hwid_limit=2,traffic_reset_days=7,renewal_days=30,renewal_remaining=2)
            inbound=Inbound(tag='db-profile',remark='Database profile',port=29001,protocol='vless',security='none',engine='xray')
            db.add_all([user,inbound]);db.commit()
            from app.services.data_restore import export_data,inspect as inspect_backup,restore
            from app.services import backups,vault
            import app.database as database
            monkeypatch.setattr(database,'engine',engine)
            monkeypatch.setattr(backups.settings,'database_url',url)
            monkeypatch.setattr(vault,'KEY_PATH',tmp_path/'test-key')
            needed='pg_dump' if make_url(url).get_backend_name()=='postgresql' else 'mariadb-dump'
            if not shutil.which(needed) and not shutil.which('mysqldump'):
                pytest.skip('Native database dump client required')
            _,encrypted=backups.create_backup('disposable-test-backup-password')
            data,secrets=inspect_backup(encrypted,'disposable-test-backup-password')
            assert len(data['tables']['vpn_users'])==1
            user.username='changed';db.commit()
            restore(db,data,secrets,owner.id)
            restored=db.query(VPNUser).one()
            assert restored.username=='portable-user' and restored.renewal_remaining==2
            db.add(VPNUser(username='after-restore'));db.commit()
            assert db.query(VPNUser).count()==2
    finally:
        Base.metadata.drop_all(engine);engine.dispose()
