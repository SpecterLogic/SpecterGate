import asyncio
import json
import os
import socket
from pathlib import Path
import pytest
import asyncssh
from sqlalchemy import create_engine
from sqlalchemy.orm import Session,sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import VPNUser,Inbound
from app.services import ssh_runtime,xray,session_control


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def test_real_ssh_tunnel_auth_routing_and_shell_rejection(monkeypatch,tmp_path):
    binary=os.getenv('XRAY_TEST_BINARY')
    if not binary:pytest.skip('Native Xray binary required')
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db=Session(engine)
    user=VPNUser(username='ssh-native',password='native-ssh-password')
    inbound=Inbound(engine='ssh',protocol='ssh',tag='ssh-native-inbound',remark='SSH',port=available_port(),listen='127.0.0.1',security='none')
    db.add_all([user,inbound]);db.commit()
    monkeypatch.setattr(ssh_runtime,'SessionLocal',sessionmaker(engine))
    relay,api_port=available_port(),available_port()
    config={'api':{'tag':'api','services':['StatsService']},'stats':{},'policy':{'levels':{'0':{'statsUserUplink':True,'statsUserDownlink':True}}},'inbounds':[{'tag':'api','listen':'127.0.0.1','port':api_port,'protocol':'dokodemo-door','settings':{'address':'127.0.0.1'}},{'tag':'sg-singbox-relay','listen':'127.0.0.1','port':relay,'protocol':'vless','settings':{'decryption':'none','clients':[{'id':user.uuid,'email':'sb:'+user.uuid}]}}],'outbounds':[{'tag':'direct','protocol':'freedom'}],'routing':{'rules':[{'type':'field','inboundTag':['api'],'outboundTag':'api'}]}}
    path=tmp_path/'ssh-relay.json';path.write_text(json.dumps(config))
    for key,value in {'xray_enabled':True,'xray_binary':binary,'xray_api_address':f'127.0.0.1:{api_port}','xray_config_path':str(path),'xray_log_path':str(tmp_path/'relay.log'),'singbox_relay_port':relay}.items():monkeypatch.setattr(xray.settings,key,value)
    xray.start_process()
    if session_control.available():session_control.call('Configure',{'limits':{},'blocks':[]})

    async def check():
        async def echo(reader,writer):
            try:
                while data:=await reader.read(4096):writer.write(data);await writer.drain()
            finally:writer.close();await writer.wait_closed()
        echo_server=await asyncio.start_server(echo,'127.0.0.1',0)
        key=asyncssh.generate_private_key('ssh-ed25519')
        listener=await asyncssh.create_server(lambda:ssh_runtime.Server(inbound.id),'127.0.0.1',inbound.port,server_host_keys=[key],encoding=None)
        known=asyncssh.import_known_hosts(f'[127.0.0.1]:{inbound.port} {key.export_public_key().decode()}')
        try:
            with pytest.raises(asyncssh.PermissionDenied):
                await asyncssh.connect('127.0.0.1',inbound.port,username=user.username,password='wrong-password',known_hosts=known,client_keys=[])
            async with asyncssh.connect('127.0.0.1',inbound.port,username=user.username,password=user.password,known_hosts=known,client_keys=[]) as connection:
                reader,writer=await connection.open_connection('127.0.0.1',echo_server.sockets[0].getsockname()[1],encoding=None)
                writer.write(b'rootless-authenticated-ssh');await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(26),timeout=5)==b'rootless-authenticated-ssh'
                with pytest.raises(asyncssh.ChannelOpenError):await connection.run('id')
                with pytest.raises(asyncssh.ChannelListenError):await connection.forward_remote_port('127.0.0.1',0,'127.0.0.1',1)
                assert xray.sync_stats(db)['ok']
                db.refresh(user);assert user.used_traffic_bytes>=52
                user.is_active=False;db.commit()
                await asyncio.wait_for(connection.wait_closed(),timeout=4)
                writer.close()
        finally:
            listener.close();await listener.wait_closed()
            echo_server.close();await echo_server.wait_closed()
    try:asyncio.run(check())
    finally:xray.stop_process();db.close();engine.dispose()
