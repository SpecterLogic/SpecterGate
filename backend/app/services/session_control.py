"""Targeted logical-flow control through the managed core's loopback API."""
import grpc
from google.protobuf.struct_pb2 import Struct
from app.config import settings
from app.models import VPNUser


def call(method, values=None):
    request = Struct()
    request.update(values or {})
    with grpc.insecure_channel(settings.xray_api_address) as channel:
        rpc = channel.unary_unary(
            f"/spectergate.control.SessionService/{method}",
            request_serializer=Struct.SerializeToString,
            response_deserializer=Struct.FromString,
        )
        result = rpc(request, timeout=4)
    from google.protobuf.json_format import MessageToDict
    values = MessageToDict(result)
    if values.get("protocol_version") != 1:
        raise RuntimeError("Unsupported session controller version")
    return values


def available():
    try:
        call("Snapshot")
        return True
    except (grpc.RpcError, RuntimeError):
        return False


def sync(db):
    from app.services.monitoring import blocks
    return call("Configure", {
        "limits": {user.uuid: int(user.device_limit or 0) for user in db.query(VPNUser).all()},
        "blocks": blocks(db),
    })
