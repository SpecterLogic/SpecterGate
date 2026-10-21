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
import sys

AWG = "--amnezia" in sys.argv
TOOL = "/usr/local/bin/awg" if AWG else "/usr/bin/wg"
INTERFACE = "sg-awg0" if AWG else "sg-wg0"
MANIFEST = Path("/opt/spectergate/backend/data/wireguard/desired.json")
RUN = Path("/run/spectergate-wg")
KEY = Path("/etc/wireguard/spectergate.key")
if AWG:
    MANIFEST = Path("/opt/spectergate/backend/data/amneziawg/desired.json")
    RUN = Path("/run/spectergate-awg")
    KEY = Path("/etc/amnezia/amneziawg/spectergate.key")


def validated_peers(data, awg=False):
    if not isinstance(data, dict) or abs(time.time() - float(data.get("updated_at", 0))) > 120:
        return []
    rows = data.get("peers", [])
    if not isinstance(rows, list) or len(rows) > 65532:
        raise ValueError("Invalid peer list")
    peers, keys, addresses = [], set(), set()
    network = ipaddress.ip_network("10.89.0.0/24" if awg else "10.88.0.0/16")
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


def validated_params(params, installed_port):
    if not isinstance(params, dict): raise ValueError("Missing AWG parameters")
    limits = {"port": (1,65535), "jc": (1,128), "jmin": (40,1280), "jmax": (40,1280), "s1": (15,1280), "s2": (15,1280), **{f"h{i}": (1,4294967295) for i in range(1,5)}}
    for key, (low, high) in limits.items():
        value = params.get(key)
        if type(value) is not int or not low <= value <= high: raise ValueError("Invalid AWG parameter")
    if type(params.get("enabled")) is not bool or params.get("server_address") != "10.89.0.1/24": raise ValueError("Invalid AWG network")
    if params["jmin"] > params["jmax"] or len({params[f"h{i}"] for i in range(1,5)}) != 4: raise ValueError("Invalid AWG obfuscation")
    if params["port"] != installed_port: raise ValueError("Reinstall with --port to change firewall and listen port")
    return params


def command(*args, input=None):
    return subprocess.check_output(args, input=input, timeout=15).decode().strip()


def clear_peers():
    for key in command(TOOL, "show", INTERFACE, "peers").split():
        if len(key) != 44 or len(base64.b64decode(key, validate=True)) != 32:
            raise ValueError("Invalid runtime peer key")
        command(TOOL, "set", INTERFACE, "peer", key, "remove")
    (RUN / "status.json").unlink(missing_ok=True)


def run():
    os.umask(0o077)
    RUN.mkdir(mode=0o750, exist_ok=True)
    os.chown(RUN, 0, grp.getgrnam("spectergate").gr_gid)
    os.chmod(RUN, 0o750)
    epoch = Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + Path(f"/sys/class/net/{INTERFACE}/ifindex").read_text().strip()
    private = KEY.read_text().strip()
    port_file = Path("/etc/amnezia/amneziawg/spectergate-port" if AWG else "/etc/wireguard/spectergate-port")
    port = int(port_file.read_text()) if port_file.exists() else (51821 if AWG else 51820)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid WireGuard listen port")
    public = command(TOOL, "pubkey", input=(private + "\n").encode())
    last = None
    applied_params = None
    while True:
        try:
            # Sample before removing peers, preserving their last traffic counters.
            peers = {}
            dump = command(TOOL, "show", INTERFACE, "dump")
            for line in dump.splitlines()[1:]:
                cols = line.split("\t")
                peers[cols[0]] = {"rx": int(cols[5]), "tx": int(cols[6]), "handshake": int(cols[4])}
            temp = RUN / "status.tmp"
            temp.write_text(json.dumps({"ready": last is not None, "updated_at": time.time(), "epoch": epoch, "public_key": public, "port": port, "peers": peers, "params": applied_params if AWG else None}))
            os.chown(temp, 0, grp.getgrnam("spectergate").gr_gid)
            os.chmod(temp, 0o640)
            temp.replace(RUN / "status.json")
            try:
                if MANIFEST.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("Manifest too large")
                body = json.loads(MANIFEST.read_text())
                desired = validated_peers(body, AWG)
                params = validated_params(body.get("params", {}), port) if AWG else None
                if AWG and not params["enabled"]: desired = []
            except (OSError, ValueError, TypeError, KeyError):
                desired = []
                params = applied_params
                # Fail closed when the panel stops refreshing its manifest.
            signature = (tuple(sorted(desired)), json.dumps(params, sort_keys=True))
            if AWG and params is None:
                raise ValueError("Waiting for valid AWG configuration")
            if signature != last:
                config = f"[Interface]\nPrivateKey = {private}\nListenPort = {port}\n"
                if AWG and params:
                    config += "".join(f"{key.upper() if key.startswith('h') else key.capitalize()} = {params[key]}\n" for key in ("jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4"))
                    config = config.replace(f"ListenPort = {port}", f"ListenPort = {params['port']}")
                for key, address in desired:
                    config += f"\n[Peer]\nPublicKey = {key}\nAllowedIPs = {address}/32\n"
                file = RUN / "sync.conf"
                file.write_text(config)
                os.chmod(file, 0o600)
                command(TOOL, "syncconf", INTERFACE, str(file))
                file.unlink(missing_ok=True)
                last = signature
                applied_params = params
        except Exception:
            (RUN / "status.json").unlink(missing_ok=True)
            try:
                clear_peers()
                last = None
            except Exception:
                logging.error("Unable to clear tunnel peers; inspect interface permissions.")
            logging.error("WireGuard synchronization failed; inspect interface/service state.")
        time.sleep(5)


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear_peers()
    else:
        run()
