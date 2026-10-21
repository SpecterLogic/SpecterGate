from sqlalchemy import create_engine, inspect, text
from app.migrations import upgrade


def test_additive_upgrade_preserves_old_accounts_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE admins (id INTEGER PRIMARY KEY, username TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO admins VALUES (1, 'existing-owner')")
        connection.exec_driver_sql("CREATE TABLE inbounds (id INTEGER PRIMARY KEY, tag TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO inbounds VALUES (7, 'existing-inbound')")
    upgrade(engine)
    upgrade(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT username,totp_enabled,totp_secret FROM admins")).one() == ("existing-owner", 0, None)
        assert connection.execute(text("SELECT tag,data_limit_bytes,expire_at FROM inbounds")).one() == ("existing-inbound", None, None)
    assert "recovery_codes_json" in {column["name"] for column in inspect(engine).get_columns("admins")}
    engine.dispose()
