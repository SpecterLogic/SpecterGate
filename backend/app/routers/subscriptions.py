from __future__ import annotations

import base64
import json
from datetime import timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DnsTunnel, Inbound, Node, SubscriptionGroup, VPNUser
from app.schemas import SubscriptionInfo
from app.services.dns import dns_links_for_user
from app.services.links import (
    build_clash_config,
    build_group_clash_config,
    links_to_base64,
    subscription_links,
)
from app.services.settings import get_setting
from app.services.exports import export_profiles


router = APIRouter(tags=["subscriptions"])


def _get_target(db: Session, token: str):
    group = db.query(SubscriptionGroup).filter(SubscriptionGroup.token == token).first()
    if group:
        return group, None
    user = db.query(VPNUser).filter(VPNUser.sub_token == token).first()
    if not user:
        raise HTTPException(status_code=404, detail="لینک اشتراک پیدا نشد.")
    return None, user


def _context(db: Session):
    inbounds = (
        db.query(Inbound)
        .filter(Inbound.is_active.is_(True))
        .order_by(Inbound.id.asc())
        .all()
    )
    nodes = {node.id: node for node in db.query(Node).all()}
    public_host = str(get_setting(db, "public_host", "127.0.0.1"))
    return inbounds, nodes, public_host


def _base_url(request: Request, db: Session) -> str:
    configured = str(get_setting(db, "subscription_base_url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _format_urls(base: str, token: str) -> dict[str, str]:
    return {format: f"{base}/sub/{token}?format={format}" for format in ("base64", "raw", "json", "clash", "singbox", "outline", "dnstt", "noizdns")}


def _headers(upload: int, download: int, limit: int | None, expire_at, title: str) -> dict[str, str]:
    total = int(limit or 0)
    expire_value = expire_at
    if expire_value is not None and expire_value.tzinfo is None:
        expire_value = expire_value.replace(tzinfo=timezone.utc)
    expire = int(expire_value.timestamp()) if expire_value else 0
    return {
        "subscription-userinfo": (
            f"upload={int(upload)}; download={int(download)}; total={total}; expire={expire}"
        ),
        "profile-update-interval": "12",
        "profile-title": f"base64:{base64.b64encode(title.encode()).decode()}",
        "cache-control": "no-store",
    }


def _group_context(group: SubscriptionGroup, db: Session, request: Request):
    inbounds, nodes, public_host = _context(db)
    active_members = [member for member in group.members if member.status == "active"]
    links: list[dict] = []
    dns_links: list[dict] = []
    tunnels = db.query(DnsTunnel).filter(DnsTunnel.is_active.is_(True)).all()
    for member in active_members:
        links.extend(subscription_links(member, inbounds, nodes, public_host))
        for link in dns_links_for_user(member, tunnels):
            item = dict(link)
            item["remark"] = f"{item['remark']} | {member.username}"
            item["member"] = member.username
            dns_links.append(item)
    return active_members, links, dns_links, inbounds, nodes, public_host


def _group_info(group: SubscriptionGroup, base: str, db: Session) -> dict:
    return {
        "username": group.name,
        "status": group.status,
        "expire_at": group.expire_at,
        "data_limit_bytes": group.data_limit_bytes,
        "used_traffic_bytes": group.used_traffic_bytes,
        "upload_bytes": sum(member.upload_bytes for member in group.members),
        "download_bytes": sum(member.download_bytes for member in group.members),
        "subscription_url": f"{base}/sub/{group.token}",
        "clash_url": f"{base}/sub/{group.token}?format=clash",
        "page_url": f"{base}/s/{group.token}",
        "format_urls": _format_urls(base, group.token),
        "subscription_type": "group",
        "group_name": group.name,
        "max_members": group.max_members,
        "members": [
            {
                "id": member.id,
                "username": member.username,
                "status": member.status,
                "used_traffic_bytes": member.used_traffic_bytes,
            }
            for member in group.members
        ],
        "panel_title": str(get_setting(db, "panel_title", "SpecterGate")),
        "panel_description": str(get_setting(db, "panel_description", "") or ""),
        "support_url": str(get_setting(db, "support_url", "") or ""),
        "announcement": str(get_setting(db, "announcement", "") or ""),
    }


@router.get("/sub/{token}", response_class=Response, include_in_schema=False)
def subscription(token: str, request: Request, format: str | None = None, db: Session = Depends(get_db)):
    if format not in {None, "base64", "raw", "json", "singbox", "clash", "outline", "dnstt", "noizdns", "wireguard"}:
        raise HTTPException(status_code=422, detail="فرمت اشتراک پشتیبانی نمی‌شود.")
    group, user = _get_target(db, token)
    if format is None and "text/html" in request.headers.get("accept", "").lower():
        return RedirectResponse(f"{_base_url(request, db)}/s/{quote(token, safe='')}", status_code=302)
    if format == "wireguard":
        from app.models import WireGuardPeer
        from app.services import wireguard
        peer = db.query(WireGuardPeer).filter_by(user_id=user.id, is_active=True).first() if user else None
        if peer is None:
            raise HTTPException(404, "WireGuard access has not been granted to this user.")
        try:
            content = wireguard.client_config(db, peer)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return Response(content, media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="{quote(user.username)}-wg.conf"', "Cache-Control": "no-store"})
    if group:
        if group.status != "active":
            raise HTTPException(status_code=403, detail="اشتراک گروهی فعال نیست.")
        members, links, dns_links, inbounds, nodes, public_host = _group_context(group, db, request)
        if not members:
            raise HTTPException(status_code=403, detail="هیچ کاربر فعالی در این اشتراک وجود ندارد.")
        title = f"{get_setting(db, 'panel_title', 'SpecterGate')} - {group.name}"
        headers = _headers(
            sum(member.upload_bytes for member in group.members),
            sum(member.download_bytes for member in group.members),
            group.data_limit_bytes,
            group.expire_at,
            title,
        )
        _client_metadata(headers, request, db, token)
        user_agent = request.headers.get("user-agent", "").lower()
        extra = _export_response(members, links, inbounds, nodes, public_host, format, user_agent, headers, dns_links)
        if extra is not None:
            return extra
        if format == "clash" or (format is None and "clash" in user_agent):
            content = build_group_clash_config(members, inbounds, nodes, public_host)
            headers["content-disposition"] = f"attachment; filename={quote(group.name)}.yaml"
            return Response(content=content, media_type="text/yaml; charset=utf-8", headers=headers)
        headers["content-disposition"] = f"attachment; filename={quote(group.name)}.txt"
        return Response(
            content=links_to_base64(links),
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    assert user is not None
    if user.status != "active":
        message = {
            "expired": "اشتراک شما منقضی شده است.",
            "limited": "حجم اشتراک شما به پایان رسیده است.",
            "disabled": "اشتراک شما غیرفعال شده است.",
        }.get(user.status, "اشتراک شما فعال نیست.")
        raise HTTPException(status_code=403, detail=message)

    inbounds, nodes, public_host = _context(db)
    links = subscription_links(user, inbounds, nodes, public_host)
    title = f"{get_setting(db, 'panel_title', 'SpecterGate')} - {user.username}"
    user_agent = request.headers.get("user-agent", "").lower()
    wants_clash = format == "clash" or (format is None and "clash" in user_agent)
    headers = _headers(user.upload_bytes, user.download_bytes, user.data_limit_bytes, user.expire_at, title)
    _client_metadata(headers, request, db, token)
    tunnels = db.query(DnsTunnel).filter(DnsTunnel.is_active.is_(True)).all()
    extra = _export_response([user], links, inbounds, nodes, public_host, format, user_agent, headers, dns_links_for_user(user, tunnels))
    if extra is not None:
        return extra

    if wants_clash:
        content = build_clash_config(user, links, inbounds, nodes, public_host)
        headers["content-disposition"] = f"attachment; filename={quote(user.username)}.yaml"
        return Response(content=content, media_type="text/yaml; charset=utf-8", headers=headers)
    headers["content-disposition"] = f"attachment; filename={quote(user.username)}.txt"
    return Response(
        content=links_to_base64(links),
        media_type="text/plain; charset=utf-8",
        headers=headers,
    )


def _client_metadata(headers, request, db, token):
    headers["profile-web-page-url"] = f"{_base_url(request, db)}/s/{quote(token, safe='')}"
    support = str(get_setting(db, "support_url", "") or "").strip()
    if support and support.isascii() and "\r" not in support and "\n" not in support:
        headers["support-url"] = support
    announcement = str(get_setting(db, "announcement", "") or "").strip()
    if announcement:
        headers["announce"] = "base64:" + base64.b64encode(announcement.encode()).decode()


def _export_response(users, links, inbounds, nodes, host, format, user_agent, headers, dns_links):
    selected = format
    if selected is None and ("sing-box" in user_agent or "singbox" in user_agent):
        selected = "singbox"
    if selected == "raw":
        return Response("\n".join(link["uri"] for link in links), media_type="text/plain", headers=headers)
    if selected in {"dnstt", "noizdns"}:
        payload = [link["uri"] for link in dns_links if link["protocol"] == selected]
        if not payload:
            raise HTTPException(status_code=422, detail="تونل سازگاری برای این اشتراک مجاز نیست.")
        return Response("\n".join(payload), media_type="text/plain", headers=headers)
    if selected == "outline":
        payload = [link["uri"] for link in links if link["protocol"] == "shadowsocks"]
        if not payload:
            raise HTTPException(status_code=422, detail="هیچ اتصال Shadowsocks برای Outline موجود نیست.")
        return Response("\n".join(payload), media_type="text/plain", headers=headers)
    if selected in {"json", "singbox"}:
        payload = export_profiles(users, inbounds, nodes, host, selected)
        if not payload:
            raise HTTPException(status_code=422, detail="هیچ اتصال سازگار با این فرمت موجود نیست.")
        return Response(json.dumps(payload, ensure_ascii=False), media_type="application/json", headers=headers)
    return None


@router.get("/sub/{token}/info", response_model=SubscriptionInfo)
def subscription_info(token: str, request: Request, db: Session = Depends(get_db)):
    group, user = _get_target(db, token)
    base = _base_url(request, db)
    formats = _format_urls(base, token)
    if user:
        from app.models import WireGuardPeer
        from app.services import wireguard
        if user.status == "active" and wireguard.server_status().get("ready") and db.query(WireGuardPeer).filter_by(user_id=user.id, is_active=True).first():
            formats["wireguard"] = f"{base}/sub/{token}?format=wireguard"
    tunnels = db.query(DnsTunnel).filter(DnsTunnel.is_active.is_(True)).all()

    if group:
        active_members, links, dns_links, _inbounds, _nodes, _host = _group_context(group, db, request)
        data = _group_info(group, base, db)
        return SubscriptionInfo(
            **data,
            links=links if group.status == "active" else [],
            dns_links=dns_links if group.status == "active" else [],
        )

    assert user is not None
    inbounds, nodes, public_host = _context(db)
    links = subscription_links(user, inbounds, nodes, public_host) if user.status == "active" else []
    dns_links = dns_links_for_user(user, tunnels) if user.status == "active" else []
    return SubscriptionInfo(
        username=user.username,
        status=user.status,
        expire_at=user.expire_at,
        data_limit_bytes=user.data_limit_bytes,
        used_traffic_bytes=user.used_traffic_bytes,
        upload_bytes=user.upload_bytes,
        download_bytes=user.download_bytes,
        links=links,
        dns_links=dns_links,
        subscription_url=f"{base}/sub/{user.sub_token}",
        clash_url=f"{base}/sub/{user.sub_token}?format=clash",
        page_url=f"{base}/s/{user.sub_token}",
        format_urls=formats,
        subscription_type="single",
        max_members=1,
        members=[
            {
                "id": user.id,
                "username": user.username,
                "status": user.status,
                "used_traffic_bytes": user.used_traffic_bytes,
            }
        ],
        panel_title=str(get_setting(db, "panel_title", "SpecterGate")),
        panel_description=str(get_setting(db, "panel_description", "") or ""),
        support_url=str(get_setting(db, "support_url", "") or ""),
        announcement=str(get_setting(db, "announcement", "") or ""),
    )
