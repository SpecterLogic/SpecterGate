from __future__ import annotations

from app.models import SubscriptionGroup
from app.schemas import SubscriptionGroupOut, SubscriptionMemberOut


def build_group_out(group: SubscriptionGroup, include_path: bool = True) -> SubscriptionGroupOut:
    return SubscriptionGroupOut(
        id=group.id,
        name=group.name,
        token=group.token,
        owner_admin_id=group.owner_admin_id,
        plan_id=group.plan_id,
        max_members=group.max_members,
        data_limit_bytes=group.data_limit_bytes,
        expire_at=group.expire_at,
        is_active=group.is_active,
        status=group.status,
        used_traffic_bytes=group.used_traffic_bytes,
        remaining_bytes=group.remaining_bytes,
        note=group.note,
        members=[
            SubscriptionMemberOut(
                id=member.id,
                username=member.username,
                status=member.status,
                used_traffic_bytes=member.used_traffic_bytes,
            )
            for member in sorted(group.members, key=lambda item: item.id)
        ],
        subscription_path=f"/sub/{group.token}" if include_path else None,
        created_at=group.created_at,
        allowed_inbound_ids=group.allowed_inbound_ids,
        allowed_dns_tunnel_ids=group.allowed_dns_tunnel_ids,
    )


def group_links(group: SubscriptionGroup, inbounds, nodes, public_host: str, service) -> list[dict]:
    links: list[dict] = []
    for member in group.members:
        if member.status != "active":
            continue
        links.extend(service(member, inbounds, nodes, public_host))
    return links
