"""Authenticated TCP SOCKS gateway for local DNSTT/NoizDNS targets.

The DNS server forwards bytes to this loopback listener. Authorization is
rechecked and traffic is committed every second, including on connection close.
"""
import asyncio
import hmac
import ipaddress
import logging
import socket
import struct
from functools import partial

from sqlalchemy import update

from app.database import SessionLocal
from app.config import settings
from app.models import DnsTunnel, VPNUser, TrafficSample
from app.services.resource_access import tunnel_allowed

logger = logging.getLogger(__name__)


def authorize(tunnel_id: int, username: str, password: bytes):
    with SessionLocal() as db:
        tunnel = db.get(DnsTunnel, tunnel_id)
        user = db.query(VPNUser).filter(VPNUser.username == username).first()
        if tunnel is None or not tunnel.is_active or not tunnel.managed_gateway or user is None:
            return None
        if not hmac.compare_digest(user.password.encode(), password) or user.status != "active" or not tunnel_allowed(user, tunnel_id):
            return None
        return user.id


def record_usage(tunnel_id: int, user_id: int, password: bytes, upload: int, download: int):
    with SessionLocal() as db:
        user = db.get(VPNUser, user_id)
        tunnel = db.get(DnsTunnel, tunnel_id)
        if user is None:
            return False
        if upload or download:
            db.execute(update(VPNUser).where(VPNUser.id == user_id).values(upload_bytes=VPNUser.upload_bytes + upload, download_bytes=VPNUser.download_bytes + download))
            db.add(TrafficSample(user_id=user_id, upload_bytes=upload, download_bytes=download))
            db.commit()
            db.refresh(user)
        return bool(tunnel and tunnel.is_active and tunnel.managed_gateway and hmac.compare_digest(user.password.encode(), password) and user.status == "active" and tunnel_allowed(user, tunnel_id))


async def resolve_target(host: str, port: int):
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM, family=socket.AF_INET if settings.dns_gateway_ipv4_only else socket.AF_UNSPEC)
    for _, _, _, _, address in records:
        ip = ipaddress.ip_address(address[0])
        if ip.is_global and not ip.is_multicast:
            return address[0], port
    raise ValueError("Private and reserved destinations are blocked")


class TunnelGateway:
    def __init__(self):
        self.servers = {}
        self.endpoints = {}
        self.errors = {}
        self.connections = set()

    async def handle(self, tunnel_id, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        remote_writer = None
        try:
            async with asyncio.timeout(15):
                version, count = await reader.readexactly(2)
                methods = await reader.readexactly(count)
                if version != 5 or 2 not in methods:
                    writer.write(b"\x05\xff")
                    await writer.drain()
                    return
                writer.write(b"\x05\x02")
                await writer.drain()
                version, length = await reader.readexactly(2)
                username = (await reader.readexactly(length)).decode("utf-8")
                password_length = (await reader.readexactly(1))[0]
                password = await reader.readexactly(password_length)
                user_id = await asyncio.to_thread(authorize, tunnel_id, username, password) if version == 1 else None
                writer.write(b"\x01\x00" if user_id else b"\x01\x01")
                await writer.drain()
                if not user_id:
                    return
                version, command, _, kind = await reader.readexactly(4)
                if version != 5 or command != 1:
                    writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                    await writer.drain()
                    return
                if kind == 1:
                    host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
                elif kind == 4:
                    host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
                elif kind == 3:
                    length = (await reader.readexactly(1))[0]
                    host = (await reader.readexactly(length)).decode("idna")
                else:
                    raise ValueError("Unsupported address kind")
                port = struct.unpack("!H", await reader.readexactly(2))[0]
                target = await resolve_target(host, port)
                remote_reader, remote_writer = await asyncio.open_connection(*target)
                writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
                await writer.drain()

            totals = [0, 0]
            stop = asyncio.Event()

            async def relay(source, destination, direction):
                while chunk := await asyncio.wait_for(source.read(65536), timeout=300):
                    destination.write(chunk)
                    totals[direction] += len(chunk)
                    await destination.drain()

            async def meter():
                while True:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=1)
                    except TimeoutError:
                        pass
                    upload, download = totals
                    totals[0] = totals[1] = 0
                    try:
                        allowed = await asyncio.to_thread(record_usage, tunnel_id, user_id, password, upload, download)
                    except Exception:
                        totals[0] += upload
                        totals[1] += download
                        raise
                    if stop.is_set() or not allowed:
                        return

            transfers = [asyncio.create_task(relay(reader, remote_writer, 0)), asyncio.create_task(relay(remote_reader, writer, 1))]
            watcher = asyncio.create_task(meter())
            try:
                await asyncio.wait([*transfers, watcher], return_when=asyncio.FIRST_COMPLETED)
            finally:
                for transfer in transfers:
                    transfer.cancel()
                await asyncio.gather(*transfers, return_exceptions=True)
                stop.set()
                try:
                    await asyncio.shield(watcher)
                finally:
                    if any(totals):
                        await asyncio.to_thread(record_usage, tunnel_id, user_id, password, *totals)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError, TimeoutError):
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Tunnel gateway connection failed for tunnel %s", tunnel_id)
        finally:
            for stream in [remote_writer, writer]:
                if stream is not None:
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except (ConnectionError, OSError):
                        pass
            self.connections.discard(task)

    @staticmethod
    def desired():
        with SessionLocal() as db:
            return {t.id: (t.target_host, t.target_port) for t in db.query(DnsTunnel).all() if t.is_active and t.managed_gateway}

    async def reconcile(self):
        desired = await asyncio.to_thread(self.desired)
        for tunnel_id in list(self.servers):
            if self.endpoints[tunnel_id] != desired.get(tunnel_id):
                self.servers.pop(tunnel_id).close()
                self.endpoints.pop(tunnel_id, None)
        for tunnel_id, endpoint in desired.items():
            if tunnel_id in self.servers:
                continue
            try:
                if not ipaddress.ip_address(endpoint[0]).is_loopback:
                    raise ValueError("Only loopback listeners are allowed")
                self.servers[tunnel_id] = await asyncio.start_server(partial(self.handle, tunnel_id), *endpoint, limit=131072)
                self.endpoints[tunnel_id] = endpoint
                self.errors.pop(tunnel_id, None)
            except (OSError, ValueError) as exc:
                self.errors[tunnel_id] = str(exc)

    async def run(self, stop):
        try:
            while not stop.is_set():
                try:
                    await self.reconcile()
                except Exception:
                    logger.exception("Tunnel gateway reconciliation failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
        finally:
            for server in self.servers.values():
                server.close()
            await asyncio.gather(*(s.wait_closed() for s in self.servers.values()))
            tasks = list(self.connections)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.servers.clear()
