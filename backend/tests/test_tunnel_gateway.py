import asyncio
import socket
import struct
import uuid
from functools import partial

import pytest

from app.database import SessionLocal
from app.models import DnsTunnel, VPNUser
from app.services import tunnel_gateway


def test_socks_auth_traffic_and_live_access_revocation(client, auth, monkeypatch):
    suffix = uuid.uuid4().hex[:7]
    tunnel = client.post("/api/dns-tunnels", headers=auth, json={"name": "Gateway test " + suffix, "domain": f"t{suffix}.example.com", "upstream_port": 5590}).json()
    user = client.post("/api/users", headers=auth, json={"username": "socks_" + suffix, "allowed_dns_tunnel_ids": [tunnel["id"]]}).json()
    with SessionLocal() as db:
        t = db.get(DnsTunnel, tunnel["id"])
        t.gateway_config.enabled = True
        password = db.get(VPNUser, user["id"]).password
        db.commit()

    async def run():
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async def resolve(host, port):
            return host, port

        monkeypatch.setattr(tunnel_gateway, "resolve_target", resolve)
        gateway = tunnel_gateway.TunnelGateway()
        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        server = await asyncio.start_server(partial(gateway.handle, tunnel["id"]), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        target_port = target.sockets[0].getsockname()[1]

        async def authenticate(secret):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"\x05\x01\x02")
            await writer.drain()
            assert await reader.readexactly(2) == b"\x05\x02"
            username = user["username"].encode()
            writer.write(b"\x01" + bytes([len(username)]) + username + bytes([len(secret)]) + secret)
            await writer.drain()
            return reader, writer, await reader.readexactly(2)

        try:
            reader, writer, reply = await authenticate(b"bad-password")
            assert reply == b"\x01\x01"
            writer.close()
            await writer.wait_closed()
            reader, writer, reply = await authenticate(password.encode())
            assert reply == b"\x01\x00"
            writer.write(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", target_port))
            await writer.drain()
            assert (await reader.readexactly(10))[1] == 0
            writer.write(b"hello-proxy")
            await writer.drain()
            assert await reader.readexactly(11) == b"hello-proxy"
            revoked = await asyncio.to_thread(client.patch, f"/api/users/{user['id']}", headers=auth, json={"allowed_dns_tunnel_ids": []})
            assert revoked.status_code == 200
            assert await asyncio.wait_for(reader.read(1), timeout=4) == b""
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            target.close()
            await server.wait_closed()
            await target.wait_closed()
            if gateway.connections:
                await asyncio.gather(*list(gateway.connections), return_exceptions=True)

    asyncio.run(run())
    with SessionLocal() as db:
        u = db.get(VPNUser, user["id"])
        assert u.upload_bytes == 11
        assert u.download_bytes == 11
        db.get(DnsTunnel, tunnel["id"]).gateway_config.enabled = False
        db.commit()


def test_gateway_blocks_private_targets():
    with pytest.raises(ValueError):
        asyncio.run(tunnel_gateway.resolve_target("127.0.0.1", 80))


def test_gateway_requires_loopback_and_unique_port(client, auth):
    suffix = uuid.uuid4().hex[:7]
    payload = {"name": "Guard " + suffix, "domain": f"guard{suffix}.example.com", "upstream_port": 5591, "target_host": "0.0.0.0", "managed_gateway": True}
    assert client.post("/api/dns-tunnels", headers=auth, json=payload).status_code == 400
