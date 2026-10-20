import json
import os
from pathlib import Path
import sys

import pytest

from app.services import maintenance, xray


@pytest.mark.skipif(not os.getenv('XRAY_TEST_BINARY'), reason='XRAY_TEST_BINARY not supplied')
def test_core_starts_from_relative_config_path(tmp_path, monkeypatch):
    binary = str(Path(os.environ['XRAY_TEST_BINARY']).resolve())
    monkeypatch.chdir(tmp_path)
    path = Path('data/xray/config.json')
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'log': {'loglevel': 'warning'}, 'outbounds': [{'protocol': 'freedom'}]}))
    monkeypatch.setattr(xray.settings, 'xray_enabled', True)
    monkeypatch.setattr(xray.settings, 'xray_binary', binary)
    monkeypatch.setattr(xray.settings, 'xray_config_path', str(path))
    monkeypatch.setattr(xray.settings, 'xray_log_path', 'data/xray/core.log')
    try:
        xray.start_process()
        assert xray.xray_status()['running']
    finally:
        xray.stop_process()


def test_core_immediate_exit_is_reported(tmp_path, monkeypatch):
    config = tmp_path / 'config.json'
    config.write_text('{}')
    monkeypatch.setattr(xray.settings, 'xray_enabled', True)
    monkeypatch.setattr(xray.settings, 'xray_binary', sys.executable)
    monkeypatch.setattr(xray.settings, 'xray_config_path', str(config))
    monkeypatch.setattr(xray.settings, 'xray_log_path', str(tmp_path / 'core.log'))
    try:
        with pytest.raises(RuntimeError, match='exited during startup'):
            xray.start_process()
    finally:
        xray.stop_process()


def test_restart_recovery_respects_operator_stop(client, monkeypatch, tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{}')
    monkeypatch.setattr(xray.settings, 'xray_enabled', True)
    monkeypatch.setattr(xray.settings, 'xray_config_path', str(config))
    monkeypatch.setattr(xray, 'xray_status', lambda: {'running': False})
    applied = []
    monkeypatch.setattr(xray, 'apply_config', lambda db: applied.append(True) or {'ok': True})
    monkeypatch.setattr(maintenance, 'get_setting', lambda *args: False)
    maintenance.reconcile()
    assert applied == []
    monkeypatch.setattr(maintenance, 'get_setting', lambda *args: True)
    maintenance.reconcile()
    assert applied == [True]
