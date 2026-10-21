from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import Node


def test_routing_path(
    db: Session,
    target_domain: str | None = None,
    target_ip: str | None = None,
    target_port: int | None = None,
    network: str = "tcp",
    inbound_tag: str | None = None,
    node_id: int | None = None,
    protocol: str | None = None,
) -> dict[str, Any]:
    from fastapi import HTTPException
    from app.services import xray_rpc, xray
    import grpc
    if node_id is not None:
        node = db.get(Node, node_id)
        if node is None:
            raise HTTPException(404, "Node not found")
        if not node.is_local:
            raise HTTPException(409, "Route diagnostics require the local core; remote node RPC is not exposed.")
    if not xray.xray_status()["running"]:
        raise HTTPException(503, "Start and apply the local core configuration before testing a route.")
    if target_ip:
        try:
            ipaddress.ip_address(target_ip)
        except ValueError:
            raise HTTPException(422, "Invalid target IP") from None
    try:
        result = xray_rpc.route(target_domain, target_ip, target_port, network, inbound_tag, protocol)
    except grpc.RpcError:
        # No approximate fallback: unavailable RPC or incomplete context must
        # not be reported as a successful test of the active route.
        raise HTTPException(422, "The active core could not select a route. Provide port/inbound where needed and apply configuration first.") from None
    return {"outbound": result.outbound_tag, "rule_index": None,
            "rule_name": "Xray RoutingService.TestRoute", "reason": "Selected by the running core and its loaded geodata.",
            "matched": True}


def check_connectivity(
    target_host: str,
    target_port: int = 443,
    timeout_sec: float = 3.0,
) -> dict[str, Any]:
    target_host = target_host.strip()
    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(target_host)
    except Exception as e:
        return {
            "reachable": False,
            "host": target_host,
            "port": target_port,
            "latency_ms": None,
            "resolved_ip": None,
            "error": f"خطا در تحلیل نام دامنه (DNS Resolution Failed): {e}",
        }

    start = time.perf_counter()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((resolved_ip, target_port))
        sock.close()
        latency_ms = round((time.perf_counter() - start) * 1000.0, 1)
        return {
            "reachable": True,
            "host": target_host,
            "port": target_port,
            "latency_ms": latency_ms,
            "resolved_ip": resolved_ip,
            "error": None,
        }
    except Exception as exc:
        sock.close()
        return {
            "reachable": False,
            "host": target_host,
            "port": target_port,
            "latency_ms": None,
            "resolved_ip": resolved_ip,
            "error": str(exc),
        }
