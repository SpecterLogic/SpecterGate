import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Inbound, VPNUser
from app.services import singbox_runtime as runtime, xray


def port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def certificate(folder):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=2)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False).sign(key, hashes.SHA256())
    pem, private = folder/'cert.pem', folder/'key.pem'
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return str(pem), str(private)


@pytest.mark.parametrize('protocol', ['vless','hysteria2','tuic','shadowsocks','shadowtls'])
def test_native_payload_and_shared_xray_accounting(protocol, monkeypatch, tmp_path):
    sb, xr = os.getenv('SINGBOX_TEST_BINARY'), os.getenv('XRAY_TEST_BINARY')
    if not sb or not xr:
        pytest.skip('Native Sing-box and Xray binaries required')
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db = Session(engine)
    cert, key = certificate(tmp_path)
    decoy = None
    extra = None
    if protocol == 'shadowtls':
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(cert,key)
        class TLSDecoy(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                try:
                    with context.wrap_socket(self.request,server_side=True) as stream:
                        stream.recv(1024)
                except (OSError,ValueError):
                    pass
        decoy = socketserver.ThreadingTCPServer(('127.0.0.1',0),TLSDecoy)
        decoy.daemon_threads=True
        threading.Thread(target=decoy.serve_forever,daemon=True).start()
        extra=json.dumps({'shadowtls_handshake':'localhost','shadowtls_handshake_port':decoy.server_address[1]})
    ib = Inbound(extra_json=extra,engine='singbox' , tag='native-second-engine', remark='Native', protocol=protocol, port=port(), listen='127.0.0.1', network='tcp', security='none' if protocol in {'shadowsocks','shadowtls'} else 'tls', sni='localhost', tls_cert_path=cert, tls_key_path=key)
    user = VPNUser(username='native-user', password='test-password-for-native-server')
    db.add_all([ib,user]);db.commit()
    monkeypatch.setattr(runtime.settings,'singbox_binary',sb)
    monkeypatch.setattr(runtime.settings,'singbox_config_path',str(tmp_path/'singbox.json'))
    monkeypatch.setattr(runtime.settings,'singbox_relay_port',port())
    monkeypatch.setattr(xray.settings,'xray_api_address',f'127.0.0.1:{port()}')
    monkeypatch.setattr(xray.settings,'xray_binary',xr)
    monkeypatch.setattr(xray.settings,'xray_enabled',True)
    monkeypatch.setattr(xray.settings,'xray_config_path',str(tmp_path/'xray.json'))
    monkeypatch.setattr(xray.settings,'xray_log_path',str(tmp_path/'xray.log'))
    original = xray.generate_config
    def generated(db, node=None):
        config,*rest = original(db,node)
        # Test-only echo endpoint; production private-network protection stays on.
        config['routing']['rules']=[rule for rule in config['routing']['rules'] if rule.get('ip')!=['geoip:private']]
        return config,*rest
    monkeypatch.setattr(xray,'generate_config',generated)

    class Echo(socketserver.BaseRequestHandler):
        def handle(self):
            while data:=self.request.recv(4096):
                self.request.sendall(data)
    echo=socketserver.ThreadingTCPServer(('127.0.0.1',0),Echo)
    echo.daemon_threads=True
    threading.Thread(target=echo.serve_forever,daemon=True).start()
    client_process=None
    try:
        assert runtime.apply(db)['ok']
        outbounds=runtime.client_outbounds(ib,user,'127.0.0.1','proxy')
        if 'tls' in outbounds[0]:outbounds[0]['tls']['certificate_path']=cert
        client_port=port()
        config={'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':client_port}], 'outbounds':outbounds, 'route':{'final':'proxy'}}
        path=tmp_path/'client.json';path.write_text(json.dumps(config),encoding='utf-8')
        client_process=subprocess.Popen([sb,'run','-c',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                connection=socket.create_connection(('127.0.0.1',client_port),timeout=5)
                break
            except OSError:
                assert client_process.poll() is None
                time.sleep(.1)
        else:pytest.fail('Client did not listen')
        with connection:
            connection.sendall(b'\x05\x01\x00');assert connection.recv(2)==b'\x05\x00'
            connection.sendall(b'\x05\x01\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('>H',echo.server_address[1]))
            response=b''
            while len(response)<10:
                chunk=connection.recv(10-len(response));assert chunk;response+=chunk
            assert response[1]==0
            connection.sendall(b'authenticated-second-engine')
            assert connection.recv(4096)==b'authenticated-second-engine'
        time.sleep(.2)
        assert xray.sync_stats(db)['ok']
        db.refresh(user)
        assert user.upload_bytes>=len(b'authenticated-second-engine')
        assert user.download_bytes>=len(b'authenticated-second-engine')
        # Quota/deactivation removes authorization from the second engine.
        user.is_active=False;db.commit()
        assert runtime.generate(db)['inbounds']==[]
        assert runtime.apply(db)['ok'] and not runtime.status()['running']
    finally:
        if client_process:
            client_process.terminate();client_process.wait(timeout=10)
        runtime.stop();xray.stop_process()
        echo.shutdown();echo.server_close();db.close();engine.dispose()
        if decoy:decoy.shutdown();decoy.server_close()
