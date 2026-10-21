"""Typed calls to the loopback-only API of the installed Xray core."""
import ipaddress

import grpc

from app.config import settings
from app.proto import xray_pb2 as wire


def call(service, method, request, response):
    with grpc.insecure_channel(settings.xray_api_address) as channel:
        rpc = channel.unary_unary(
            f"/xray.app.{service}.command.{'Routing' if service == 'router' else 'Stats'}Service/{method}",
            request_serializer=lambda message: message.SerializeToString(),
            response_deserializer=response.FromString,
        )
        return rpc(request, timeout=4)


def route(domain=None, ip=None, port=None, network="tcp", inbound=None, protocol=None, user=None, source_ip=None):
    context = wire.RoutingContext(
        inbound_tag=inbound or "", network=2 if network == "tcp" else 3,
        target_port=port or 0, target_domain=domain or "", protocol=protocol or "", user=user or "",
    )
    if ip:
        context.target_ips.append(ipaddress.ip_address(ip).packed)
    if source_ip:
        context.source_ips.append(ipaddress.ip_address(source_ip).packed)
    return call("router", "TestRoute", wire.TestRouteRequest(routing_context=context), wire.RoutingContext)


def online_users():
    names = call("stats", "GetAllOnlineUsers", wire.Empty(), wire.OnlineUsers).users
    return [name.removeprefix("user>>>").removesuffix(">>>online") for name in names]


def online_ips(email):
    request = wire.StatsRequest(name=f"user>>>{email}>>>online")
    return dict(call("stats", "GetStatsOnlineIpList", request, wire.OnlineIps).ips)
