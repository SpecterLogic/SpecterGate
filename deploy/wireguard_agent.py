#!/usr/bin/env python3
"""Privileged companion with a fixed interface, port and address pool.

Only validated public keys and addresses cross from the panel into this service.
The root-owned server private key is never readable by the panel process.
"""
import base64
import grp
import ipaddress
import json
import logging
import os
from pathlib import Path
import subprocess
import time

INTERFACE = "sg-wg0"
MANIFEST = Path("/opt/spectergate/backend/data/wireguard/desired.json")
RUN = Path("/run/spectergate-wg")
KEY = Path("/etc/wireguard/spectergate.key")


def validated_peers(data):
    if not isinstance(data, dict) or abs(time.time() - float(data.get("updated_at", 0))) > 120:
        return []
    rows = data.get("peers", [])
    if not isinstance(rows, list) or len(rows) > 65532:
        raise ValueError("Invalid peer list")
    peers, keys, addresses = [], set(), set()
    network = ipaddress.ip_network("10.88.0.0/16")
    for row in rows:
        key = row["public_key"]
        if not isinstance(key, str) or len(key) != 44 or len(base64.b64decode(key, validate=True)) != 32:
            raise ValueError("Invalid public key")
        address = ipaddress.ip_address(row["address"])
        if address not in network or int(address) <= int(network.network_address) + 1 or address == network.broadcast_address:
            raise ValueError("Address outside reserved peer pool")
        if key in keys or str(address) in addresses:
            raise ValueError("Duplicate peer")
        keys.add(key)
        addresses.add(str(address))
        peers.append((key, str(address)))
    return peers


def command(*args, input=None):
    return subprocess.check_output(args, input=input, timeout=15).decode().strip()


def run():
    os.umask(0o077)
    RUN.mkdir(mode=0o750, exist_ok=True)
    os.chown(RUN, 0, grp.getgrnam("spectergate").gr_gid)
    os.chmod(RUN, 0o750)
    epoch = Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + Path(f"/sys/class/net/{INTERFACE}/ifindex").read_text().strip()
    private = KEY.read_text().strip()
    port_file = Path("/etc/wireguard/spectergate-port")
    port = int(port_file.read_text()) if port_file.exists() else 51820
    if not 1 <= port <= 65535:
        raise ValueError("Invalid WireGuard listen port")
    public = command("wg", "pubkey", input=(private + "\n").encode())
    last = None
    while True:
        try:
            # Sample before removing peers, preserving their last traffic counters.
            peers = {}
            dump = command("wg", "show", INTERFACE, "dump")
            for line in dump.splitlines()[1:]:
                cols = line.split("\t")
                peers[cols[0]] = {"rx": int(cols[5]), "tx": int(cols[6]), "handshake": int(cols[4])}
            temp = RUN / "status.tmp"
            temp.write_text(json.dumps({"ready": last is not None, "updated_at": time.time(), "epoch": epoch, "public_key": public, "port": port, "peers": peers}))
            os.chown(temp, 0, grp.getgrnam("spectergate").gr_gid)
            os.chmod(temp, 0o640)
            temp.replace(RUN / "status.json")
            try:
                if MANIFEST.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("Manifest too large")
                desired = validated_peers(json.loads(MANIFEST.read_text()))
            except (OSError, ValueError, TypeError, KeyError):
                desired = []  # Fail closed when the panel stops refreshing its manifest.
            signature = tuple(sorted(desired))
            if signature != last:
                config = f"[Interface]\nPrivateKey = {private}\nListenPort = {port}\n"
                for key, address in desired:
                    config += f"\n[Peer]\nPublicKey = {key}\nAllowedIPs = {address}/32\n"
                file = RUN / "sync.conf"
                file.write_text(config)
                os.chmod(file, 0o600)
                command("wg", "syncconf", INTERFACE, str(file))
                file.unlink(missing_ok=True)
                last = signature
        except Exception:
            (RUN / "status.json").unlink(missing_ok=True)
            logging.error("WireGuard synchronization failed; inspect interface/service state.")
        time.sleep(5)


if __name__ == "__main__":
    run()
