import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import threading
import time
import uuid
import pytest
from app.models import Inbound,VPNUser
from app.services import core_crypto,xray
from app.services.inbound_options import AdvancedInbound,TLSOptions,RealityOptions,Fallback
from test_singbox_runtime import certificate,port


def native(monkeypatch):
    binary=os.getenv('XRAY_TEST_BINARY')
    if not binary:pytest.skip('Native Xray required')
    monkeypatch.setattr(xray.settings,'xray_binary',binary)
    return binary


def test_generated_ech_encryption_and_mldsa_keys_pass_native_validation(monkeypatch,tmp_path):
    binary=native(monkeypatch)
    ech=core_crypto.generate('ech','example.com')
    encryption=core_crypto.generate('vlessenc')
    signature=core_crypto.generate('mldsa65')
    pem,key=certificate(tmp_path)
    user=VPNUser(username='crypto-user',uuid=str(uuid.uuid4()),password='test-password',sub_token='test-native-subscription-token',is_active=True)
    adv=AdvancedInbound(tls=TLSOptions(**ech),**encryption)
    inbound=Inbound(id=1,tag='crypto-inbound',remark='Crypto',engine='xray',protocol='vless',port=port(),network='tcp',security='tls',is_active=True,tls_cert_path=pem,tls_key_path=key,sni='localhost',extra_json=adv.model_dump_json())
    server,*_=xray._build_inbound(inbound,[user])
    config={'inbounds':[server],'outbounds':[{'protocol':'freedom'}]}
    path=tmp_path/'crypto.json';path.write_text(json.dumps(config))
    result=subprocess.run([binary,'run','-test','-c',str(path)],capture_output=True)
    assert result.returncode==0,'Native TLS/ECH/VLESS Encryption configuration rejected'
    keys=xray.generate_keypair()
    inbound.security='reality';inbound.reality_private_key=keys['private_key'];inbound.reality_public_key=keys['public_key'];inbound.reality_short_id=keys['short_id'];inbound.reality_dest='www.cloudflare.com:443'
    inbound.extra_json=AdvancedInbound(reality=RealityOptions(**signature)).model_dump_json()
    server,*_=xray._build_inbound(inbound,[user]);config['inbounds']=[server];path.write_text(json.dumps(config))
    result=subprocess.run([binary,'run','-test','-c',str(path)],capture_output=True)
    assert result.returncode==0,'Native ML-DSA-65 Reality configuration rejected'
    from app.services.exports import export_profiles
    # JSON client exports must never carry server decryption/seed/ECH keys.
    client=export_profiles([user],[inbound],{},'example.com','json')
    assert signature['mldsa65Seed'] not in json.dumps(client)
    assert signature['mldsa65Verify'] in json.dumps(client)


def test_tls_fallback_reaches_local_http_service_on_shared_port(monkeypatch,tmp_path):
    binary=native(monkeypatch)
    class HTTP(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(4096)
            self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\nfallback-ok')
    http=socketserver.ThreadingTCPServer(('127.0.0.1',0),HTTP);http.daemon_threads=True
    threading.Thread(target=http.serve_forever,daemon=True).start()
    pem,key=certificate(tmp_path)
    inbound=Inbound(id=1,tag='fallback-inbound',remark='Shared port',engine='xray',protocol='vless',listen='127.0.0.1',port=port(),network='tcp',security='tls',is_active=True,tls_cert_path=pem,tls_key_path=key,sni='localhost',extra_json=AdvancedInbound(fallbacks=[Fallback(dest=http.server_address[1])]).model_dump_json())
    user=VPNUser(username='fallback-user',uuid=str(uuid.uuid4()),password='test-password',sub_token='test-native-subscription-token',is_active=True)
    server,*_=xray._build_inbound(inbound,[user])
    path=tmp_path/'fallback.json';path.write_text(json.dumps({'inbounds':[server],'outbounds':[{'protocol':'freedom'}]}))
    process=subprocess.Popen([binary,'run','-c',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:connection=socket.create_connection(('127.0.0.1',inbound.port),timeout=3);break
            except OSError:assert process.poll() is None;time.sleep(.1)
        else:pytest.fail('TLS fallback listener did not start')
        with ssl.create_default_context(cafile=pem).wrap_socket(connection,server_hostname='localhost') as stream:
            stream.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            response=b''
            while chunk:=stream.recv(4096):response+=chunk
        assert response.startswith(b'HTTP/1.1 200') and response.endswith(b'fallback-ok')
    finally:
        process.terminate();process.wait(timeout=10);http.shutdown();http.server_close()
