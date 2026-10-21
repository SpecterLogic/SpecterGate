from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.deps import get_client_ip, get_db, require_permission
from app.models import Admin, Node
from app.services.audit import write_audit
from app.services.hosts_dns import DnsConfig, HostEntry, get_dns_config, save_dns_config

router = APIRouter(prefix="/dns-hosts", tags=["dns-hosts"])


def _validate_node(db: Session, node_id: int | None) -> None:
    if node_id is not None:
        node = db.get(Node, node_id)
        if not node:
            raise HTTPException(status_code=404, detail="نود مورد نظر یافت نشد.")


@router.get("", response_model=DnsConfig)
def read_dns_config(
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("dns.read")),
    db: Session = Depends(get_db),
):
    _validate_node(db, node_id)
    return get_dns_config(db, node_id)


@router.put("", response_model=DnsConfig)
def update_dns_config(
    payload: DnsConfig,
    request: Request,
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("dns.manage")),
    db: Session = Depends(get_db),
):
    _validate_node(db, node_id)
    saved = save_dns_config(db, payload, node_id)
    write_audit(
        db,
        admin,
        "update_dns_hosts",
        "dns_config",
        str(node_id) if node_id else "global",
        f"تنظیمات DNS به‌روزرسانی شد. تعداد هاست‌ها: {len(saved.hosts)}، سرورها: {len(saved.servers)}",
        get_client_ip(request),
    )
    return saved


@router.post("/hosts", response_model=list[HostEntry])
def upsert_host_entry(
    entry: HostEntry,
    request: Request,
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("dns.manage")),
    db: Session = Depends(get_db),
):
    _validate_node(db, node_id)
    config = get_dns_config(db, node_id)
    # Check if host exists, update it, else append
    existing_index = next((i for i, h in enumerate(config.hosts) if h.domain == entry.domain), None)
    if existing_index is not None:
        config.hosts[existing_index] = entry
    else:
        config.hosts.append(entry)

    save_dns_config(db, config, node_id)
    write_audit(
        db,
        admin,
        "upsert_host_entry",
        "host_mapping",
        entry.domain,
        f"نگاشت دامنه {entry.domain} به {entry.ips} ثبت شد.",
        get_client_ip(request),
    )
    return config.hosts


@router.delete("/hosts/{domain:path}", response_model=list[HostEntry])
def delete_host_entry(
    domain: str,
    request: Request,
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("dns.manage")),
    db: Session = Depends(get_db),
):
    _validate_node(db, node_id)
    clean_domain = domain.strip().lower()
    config = get_dns_config(db, node_id)
    initial_len = len(config.hosts)
    config.hosts = [h for h in config.hosts if h.domain != clean_domain]
    if len(config.hosts) == initial_len:
        raise HTTPException(status_code=404, detail="نگاشت مورد نظر یافت نشد.")

    save_dns_config(db, config, node_id)
    write_audit(
        db,
        admin,
        "delete_host_entry",
        "host_mapping",
        clean_domain,
        f"نگاشت دامنه {clean_domain} حذف شد.",
        get_client_ip(request),
    )
    return config.hosts
