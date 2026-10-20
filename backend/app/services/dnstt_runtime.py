"""Supervise native DNSTT processes and a bounded authoritative UDP multiplexer."""
import asyncio
import ipaddress
import os
from pathlib import Path
import shutil
import sys

from app.config import BASE_DIR, settings
from app.database import SessionLocal
from app.models import DnsTunnel


def qname(packet):
    if len(packet) < 13 or len(packet) > 4096: return None
    labels, cursor = [], 12
    while cursor < len(packet):
        size = packet[cursor]; cursor += 1
        if size == 0: return ".".join(labels).lower()
        if size > 63 or cursor + size > len(packet): return None
        try: labels.append(packet[cursor:cursor+size].decode("ascii"))
        except UnicodeDecodeError: return None
        cursor += size
    return None


class Answer(asyncio.DatagramProtocol):
    def __init__(self, future): self.future = future
    def datagram_received(self, data, _):
        if not self.future.done(): self.future.set_result(data)
    def error_received(self, error):
        if not self.future.done(): self.future.set_exception(error)


class Multiplexer(asyncio.DatagramProtocol):
    def __init__(self, runtime): self.runtime = runtime; self.tasks = set()
    def connection_made(self, transport): self.transport = transport
    def datagram_received(self, data, client):
        name = qname(data)
        if not name or len(self.tasks) >= 256: return
        candidates = [(domain, port) for domain, port in self.runtime.routes.items() if name == domain or name.endswith("." + domain)]
        if not candidates:
            response = bytearray(data); response[2] |= 128; response[3] = (response[3] & 240) | 2
            self.transport.sendto(response, client); return
        port = max(candidates, key=lambda item: len(item[0]))[1]
        task = asyncio.create_task(self.forward(data, client, port))
        self.tasks.add(task); task.add_done_callback(self.tasks.discard)
    async def forward(self, query, client, port):
        transport = None
        try:
            loop = asyncio.get_running_loop(); future = loop.create_future()
            transport, _ = await loop.create_datagram_endpoint(lambda: Answer(future), remote_addr=("127.0.0.1", port))
            transport.sendto(query)
            response = await asyncio.wait_for(future, timeout=3)
            if len(response) <= 4096 and response[:2] == query[:2]: self.transport.sendto(response, client)
        except (OSError, TimeoutError, asyncio.CancelledError): pass
        finally:
            if transport: transport.close()


class DnsttRuntime:
    def __init__(self):
        self.processes, self.signatures, self.errors, self.routes = {}, {}, {}, {}
        self.transport = self.protocol = None
        self.router_error = None

    def desired(self):
        with SessionLocal() as db:
            return {t.id: (t.domain.lower().strip("."), t.upstream_port, t.target_host, t.target_port, t.mtu, t.private_key) for t in db.query(DnsTunnel).all() if t.is_active and t.managed_gateway}

    async def stop_process(self, tunnel_id):
        process = self.processes.pop(tunnel_id)
        if process.returncode is None:
            process.terminate()
            try: await asyncio.wait_for(process.wait(), timeout=4)
            except TimeoutError: process.kill(); await process.wait()
        self.signatures.pop(tunnel_id, None)

    async def reconcile(self):
        desired = await asyncio.to_thread(self.desired)
        for identifier in list(self.processes):
            if self.signatures[identifier] != desired.get(identifier) or self.processes[identifier].returncode is not None:
                await self.stop_process(identifier)
        binary = shutil.which(settings.dnstt_binary)
        for identifier, value in desired.items():
            if identifier in self.processes: continue
            try:
                if not binary: raise ValueError("Install the native dnstt-server binary first.")
                domain, port, host, target_port, mtu, private_key = value
                if not ipaddress.ip_address(host).is_loopback: raise ValueError("Managed DNSTT requires a loopback gateway.")
                folder = BASE_DIR / "data" / "dnstt"; folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                key = folder / f"{identifier}.key"; key.write_text(private_key + "\n"); key.chmod(0o600)
                log = folder / f"{identifier}.log"
                with log.open("ab") as output:
                    os.chmod(log, 0o600)
                    self.processes[identifier] = await asyncio.create_subprocess_exec(binary, "-udp", f"127.0.0.1:{port}", "-privkey-file", str(key), "-mtu", str(mtu), domain, f"{host}:{target_port}", stdout=output, stderr=output)
                self.signatures[identifier] = value; self.errors.pop(identifier, None)
            except (OSError, ValueError): self.errors[identifier] = "DNSTT process could not start; check binary, ports and local gateway."
        self.routes = {value[0]: value[1] for key, value in desired.items() if key in self.processes and self.processes[key].returncode is None}
        if self.routes and not self.transport:
            try:
                host, port = settings.dns_listen.rsplit(":", 1)
                self.transport, self.protocol = await asyncio.get_running_loop().create_datagram_endpoint(lambda: Multiplexer(self), local_addr=(host, int(port)))
                self.router_error = None
            except (OSError, ValueError): self.router_error = "DNS listener unavailable; check public listen IP, UDP port and service capabilities."
        elif not self.routes and self.transport:
            self.transport.close(); self.transport = None

    async def run(self, stop):
        if not settings.dnstt_enabled:
            await stop.wait(); return
        try:
            while not stop.is_set():
                try: await self.reconcile()
                except Exception: self.router_error = "DNSTT reconciliation failed."
                try: await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError: pass
        finally:
            if self.transport: self.transport.close()
            if self.protocol:
                for task in list(self.protocol.tasks): task.cancel()
                await asyncio.gather(*list(self.protocol.tasks), return_exceptions=True)
            for identifier in list(self.processes): await self.stop_process(identifier)
