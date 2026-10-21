from __future__ import annotations

import ipaddress
import re
import socket
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import Inbound, Node
from app.services.routing import RoutingConfig, profile_keys
from app.services.settings import get_setting


def _domain_matches(pattern: str, target: str) -> bool:
    pattern = pattern.strip().lower()
    target = target.strip().lower()

    if pattern.startswith("domain:"):
        base = pattern.split("domain:", 1)[1]
        return target == base or target.endswith("." + base)
    if pattern.startswith("full:"):
        return target == pattern.split("full:", 1)[1]
    if pattern.startswith("keyword:"):
        return pattern.split("keyword:", 1)[1] in target
    if pattern.startswith("regexp:"):
        try:
            return bool(re.search(pattern.split("regexp:", 1)[1], target))
        except Exception:
            return False
    if pattern.startswith("geosite:"):
        # Category indicator (e.g. geosite:google)
        cat = pattern.split("geosite:", 1)[1]
        return cat in target
    return target == pattern or target.endswith("." + pattern)


def _ip_matches(pattern: str, target_ip_str: str) -> bool:
    try:
        target = ipaddress.ip_address(target_ip_str)
    except ValueError:
        return False

    pattern = pattern.strip()
    if pattern.startswith("geoip:"):
        return False  # Runtime geodata evaluated by Xray binary

    try:
        network = ipaddress.ip_network(pattern, strict=False)
        return target in network
    except ValueError:
        return False


def test_routing_path(
    db: Session,
    target_domain: str | None = None,
    target_ip: str | None = None,
    target_port: int | None = None,
    network: str = "tcp",
    inbound_tag: str | None = None,
    node_id: int | None = None,
) -> dict[str, Any]:
    key, _ = profile_keys(node_id)
    policy = RoutingConfig.model_validate(get_setting(db, key, None) or {})

    # 1. API protection
    if inbound_tag == "api":
        return {
            "outbound": "api",
            "rule_index": None,
            "rule_name": "API Service Inbound",
            "reason": "Protected system API endpoint",
            "matched": True,
        }

    # 2. Private IP block
    if target_ip:
        try:
            ip_obj = ipaddress.ip_address(target_ip)
            if ip_obj.is_private or ip_obj.is_loopback:
                return {
                    "outbound": "blocked",
                    "rule_index": None,
                    "rule_name": "Private IP Protection",
                    "reason": f"Private/loopback IP {target_ip} is blocked for security",
                    "matched": True,
                }
        except ValueError:
            pass

    # 3. Block lists
    if target_domain and any(_domain_matches(d, target_domain) for d in policy.block_domains):
        return {
            "outbound": "blocked",
            "rule_index": None,
            "rule_name": "Block Domains List",
            "reason": f"Domain {target_domain} matches block_domains",
            "matched": True,
        }
    if target_ip and any(_ip_matches(ip, target_ip) for ip in policy.block_ips):
        return {
            "outbound": "blocked",
            "rule_index": None,
            "rule_name": "Block IPs List",
            "reason": f"IP {target_ip} matches block_ips",
            "matched": True,
        }

    # 4. Direct lists
    if target_domain and any(_domain_matches(d, target_domain) for d in policy.direct_domains):
        return {
            "outbound": "direct",
            "rule_index": None,
            "rule_name": "Direct Domains List",
            "reason": f"Domain {target_domain} matches direct_domains",
            "matched": True,
        }
    if target_ip and any(_ip_matches(ip, target_ip) for ip in policy.direct_ips):
        return {
            "outbound": "direct",
            "rule_index": None,
            "rule_name": "Direct IPs List",
            "reason": f"IP {target_ip} matches direct_ips",
            "matched": True,
        }

    # 5. IPv4 domains list
    if target_domain and any(_domain_matches(d, target_domain) for d in policy.ipv4_domains):
        return {
            "outbound": "ipv4",
            "rule_index": None,
            "rule_name": "Force IPv4 Domains List",
            "reason": f"Domain {target_domain} matches ipv4_domains",
            "matched": True,
        }

    # 6. Ordered Custom Rules
    inbound_obj = db.query(Inbound).filter_by(tag=inbound_tag).first() if inbound_tag else None
    inbound_id = inbound_obj.id if inbound_obj else None

    for i, rule in enumerate(policy.rules):
        matches = True

        # Inbound check
        if rule.inbound_ids and inbound_id is not None:
            if inbound_id not in rule.inbound_ids:
                matches = False

        # Network check
        if matches and rule.network:
            if network not in rule.network.split(","):
                matches = False

        # Port check
        if matches and rule.port and target_port is not None:
            port_match = False
            for part in rule.port.split(","):
                bounds = part.strip().split("-")
                if len(bounds) == 1 and int(bounds[0]) == target_port:
                    port_match = True
                    break
                elif len(bounds) == 2 and int(bounds[0]) <= target_port <= int(bounds[1]):
                    port_match = True
                    break
            if not port_match:
                matches = False

        # Domain check
        if matches and rule.domains:
            if not target_domain or not any(_domain_matches(d, target_domain) for d in rule.domains):
                matches = False

        # IP check
        if matches and rule.ips:
            if not target_ip or not any(_ip_matches(ip, target_ip) for ip in rule.ips):
                matches = False

        if matches:
            return {
                "outbound": rule.outbound,
                "rule_index": i,
                "rule_name": f"قانون سفارشی #{i+1}",
                "reason": f"تمام شرط‌های قانون شماره {i+1} همخوانی دارند.",
                "matched": True,
            }

    # Fallback to default
    return {
        "outbound": policy.default_outbound,
        "rule_index": None,
        "rule_name": "خروجی پیش‌فرض (Default Outbound)",
        "reason": f"هیچ قانونی مطابقت نداشت؛ ترافیک به سمت {policy.default_outbound} هدایت می‌شود.",
        "matched": False,
    }


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
