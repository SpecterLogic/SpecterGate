from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.deps import get_client_ip, get_db, require_permission
from app.models import Admin, Node
from app.services.audit import write_audit
from app.services.diagnostics import check_connectivity, test_routing_path
from app.services.routing import (
    OutboundBalancer,
    RoutingConfig,
    profile_keys,
)
from app.services.settings import get_setting, set_setting

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class TestRouteRequest(BaseModel):
    target_domain: str | None = None
    target_ip: str | None = None
    target_port: int | None = Field(default=None, ge=1, le=65535)
    network: Literal["tcp", "udp"] = "tcp"
    inbound_tag: str | None = None
    node_id: int | None = None


class TestRouteResponse(BaseModel):
    outbound: str
    rule_index: int | None = None
    rule_name: str
    reason: str
    matched: bool


class PingRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=443, ge=1, le=65535)
    timeout_sec: float = Field(default=3.0, ge=0.5, le=10.0)


class PingResponse(BaseModel):
    reachable: bool
    host: str
    port: int
    latency_ms: float | None = None
    resolved_ip: str | None = None
    error: str | None = None


@router.post("/test-route", response_model=TestRouteResponse)
def simulate_route(
    payload: TestRouteRequest,
    admin: Admin = Depends(require_permission("routing.read")),
    db: Session = Depends(get_db),
):
    if not payload.target_domain and not payload.target_ip:
        raise HTTPException(status_code=400, detail="حداقل دامنه یا آدرس IP هدف باید وارد شود.")
    res = test_routing_path(
        db,
        target_domain=payload.target_domain,
        target_ip=payload.target_ip,
        target_port=payload.target_port,
        network=payload.network,
        inbound_tag=payload.inbound_tag,
        node_id=payload.node_id,
    )
    return TestRouteResponse(**res)


@router.post("/ping", response_model=PingResponse)
def ping_target(
    payload: PingRequest,
    admin: Admin = Depends(require_permission("routing.read")),
):
    res = check_connectivity(
        target_host=payload.host,
        target_port=payload.port,
        timeout_sec=payload.timeout_sec,
    )
    return PingResponse(**res)


@router.get("/balancers", response_model=list[OutboundBalancer])
def list_balancers(
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("routing.read")),
    db: Session = Depends(get_db),
):
    key, _ = profile_keys(node_id)
    policy = RoutingConfig.model_validate(get_setting(db, key, None) or {})
    return policy.balancers


@router.put("/balancers", response_model=list[OutboundBalancer])
def update_balancers(
    balancers: list[OutboundBalancer],
    request: Request,
    node_id: int | None = Query(default=None),
    admin: Admin = Depends(require_permission("routing.manage")),
    db: Session = Depends(get_db),
):
    key, _ = profile_keys(node_id)
    policy_dict = get_setting(db, key, None) or {}
    policy = RoutingConfig.model_validate(policy_dict)
    policy.balancers = balancers
    set_setting(db, key, policy.model_dump())
    write_audit(
        db,
        admin,
        "update_balancers",
        "routing_balancer",
        str(node_id) if node_id else "global",
        f"تعداد {len(balancers)} بالانسر خروجی ذخیره شد.",
        get_client_ip(request),
    )
    return policy.balancers
