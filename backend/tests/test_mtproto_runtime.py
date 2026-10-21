import json
import os
import socket
import socketserver
import struct
import threading
import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Inbound,VPNUser
from app.services import mtproto_runtime as mtg,xray


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def test_mtg_starts_and_dedicated_relay_counts_selected_user(monkeypatch,tmp_path):
    xr,binary=os.getenv('XRAY_TEST_BINARY'),os.getenv('MTG_TEST_BINARY')
    if not xr or not binary:pytest.skip('Native MTG and Xray binaries required')
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);db=Session(engine)
    user=VPNUser(username='tg-selected',password='native-mtg-password')
    other=VPNUser(username='not-selected')
    db.add_all([user,other]);db.flush()
    relay=port()
    inbound=Inbound(tag='tg-native',remark='MTProto native',protocol='mtproto',engine='mtg',listen='127.0.0.1',port=port(),security='none',extra_json=json.dumps({'mtproto_user_id':user.id,'mtproto_relay_port':relay,'mtproto_domain':'example.com'}))
    db.add(inbound);db.commit()
    for key,value in {'mtg_binary':binary,'xray_binary':xr,'xray_enabled':True,'xray_api_address':f'127.0.0.1:{port()}','xray_config_path':str(tmp_path/'data/xray/config.json'),'xray_log_path':str(tmp_path/'data/xray/xray.log')}.items():monkeypatch.setattr(xray.settings,key,value)
    original=xray.generate_config
    def generated(db,node=None):
        config,*rest=original(db,node)
        config['routing']['rules']=[r for r in config['routing']['rules'] if r.get('ip')!=['geoip:private']]
        return config,*rest
    monkeypatch.setattr(xray,'generate_config',generated)
    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data:=self.request.recv(4096):self.request.sendall(data)
    echo=socketserver.ThreadingTCPServer(('127.0.0.1',0),Echo);echo.daemon_threads=True
    threading.Thread(target=echo.serve_forever,daemon=True).start()
    try:
        assert xray.apply_config(db)['ok']
        mtg.reconcile(db)
        assert inbound.id in mtg.processes,mtg.errors
        time.sleep(.5)
        assert mtg.processes[inbound.id][1].poll() is None
        # Uses the exact per-profile SOCKS credentials embedded in MTG's config.
        _,password=mtg.credentials(inbound,user)
        with socket.create_connection(('127.0.0.1',relay),timeout=3) as connection:
            connection.sendall(b'\x05\x01\x02');assert connection.recv(2)==b'\x05\x02'
            username=user.uuid.encode();secret=password.encode()
            connection.sendall(b'\x01'+bytes([len(username)])+username+bytes([len(secret)])+secret)
            assert connection.recv(2)==b'\x01\x00'
            connection.sendall(b'\x05\x01\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('>H',echo.server_address[1]))
            response=b''
            while len(response)<10:
                part=connection.recv(10-len(response));assert part;response+=part
            assert response[1]==0
            connection.sendall(b'tg-metered-relay');assert connection.recv(4096)==b'tg-metered-relay'
        time.sleep(.1)
        assert xray.sync_stats(db)['ok']
        db.refresh(user);db.refresh(other)
        assert user.used_traffic_bytes>=32 and other.used_traffic_bytes==0
        user.is_active=False;db.commit();mtg.reconcile(db)
        assert inbound.id not in mtg.processes
    finally:
        mtg.stop();xray.stop_process();echo.shutdown();echo.server_close();db.close();engine.dispose()
