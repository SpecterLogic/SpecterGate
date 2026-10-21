"""Validated advanced inbound settings shared by server and client exporters."""
import ipaddress
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Sniffing(StrictModel):
    enabled: bool = True
    destOverride: list[Literal['http', 'tls', 'quic', 'fakedns']] = Field(default_factory=lambda: ['http', 'tls', 'quic'], max_length=4)
    routeOnly: bool = False
    metadataOnly: bool = False
    domainsExcluded: list[str] = Field(default_factory=list, max_length=200)


class TLSOptions(StrictModel):
    echServerKeys: str = Field(default='', max_length=16384)
    echConfigList: str = Field(default='', max_length=16384)
    minVersion: Literal['1.2', '1.3'] = '1.2'
    maxVersion: Literal['1.2', '1.3'] = '1.3'
    cipherSuites: str = Field(default='', max_length=2000)
    curvePreferences: list[str] = Field(default_factory=list, max_length=10)
    rejectUnknownSni: bool = False
    disableSystemRoot: bool = False
    enableSessionResumption: bool = False
    ech: bool = False
    echConfig: str = Field(default='', max_length=2000)
    mldsa65: bool = False

    @model_validator(mode='after')
    def versions(self):
        if self.minVersion > self.maxVersion:
            raise ValueError('TLS minimum version exceeds maximum version.')
        return self


class FallbackLimit(StrictModel):
    afterBytes: int = Field(default=0, ge=0, le=2**53-1)
    bytesPerSec: int = Field(default=0, ge=0, le=2**53-1)
    burstBytesPerSec: int = Field(default=0, ge=0, le=2**53-1)


class RealityOptions(StrictModel):
    mldsa65Seed: str = Field(default='', max_length=128)
    mldsa65Verify: str = Field(default='', max_length=8192)
    xver: Literal[0, 1, 2] = 0
    serverNames: list[str] = Field(default_factory=list, max_length=30)
    shortIds: list[str] = Field(default_factory=list, max_length=30)
    maxTimeDiff: int = Field(default=0, ge=0, le=86400000)
    minClientVer: str = Field(default='', max_length=20, pattern=r'^(?:\d{1,3}\.\d{1,3}\.\d{1,3})?$')
    maxClientVer: str = Field(default='', max_length=20, pattern=r'^(?:\d{1,3}\.\d{1,3}\.\d{1,3})?$')
    spiderX: str = Field(default='/', max_length=255, pattern=r'^/')
    limitFallbackUpload: FallbackLimit = Field(default_factory=FallbackLimit)
    limitFallbackDownload: FallbackLimit = Field(default_factory=FallbackLimit)
    finalMask: bool = False
    finalMaskConfig: str = Field(default='', max_length=1000)

    @field_validator('shortIds')
    @classmethod
    def short_ids(cls, values):
        if any(not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}', value) for value in values):
            raise ValueError('Reality Short IDs must contain an even number of hexadecimal characters, at most 16.')
        return values

    @field_validator('serverNames')
    @classmethod
    def server_names(cls, values):
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', value) for value in values):
            raise ValueError('Invalid Reality server name.')
        return values


class Sockopt(StrictModel):
    tcpFastOpen: bool = False
    tcpKeepAliveIdle: int = Field(default=300, ge=0, le=86400)
    tcpKeepAliveInterval: int = Field(default=30, ge=0, le=86400)
    tcpUserTimeout: int = Field(default=0, ge=0, le=86400000)
    tcpCongestion: str = Field(default='', max_length=30, pattern=r'^[a-zA-Z0-9_-]*$')
    interface: str = Field(default='', max_length=64, pattern=r'^[a-zA-Z0-9_.:-]*$')
    domainStrategy: Literal['AsIs', 'UseIP', 'UseIPv4', 'UseIPv6', 'UseIPv4v6', 'UseIPv6v4', 'ForceIP', 'ForceIPv4', 'ForceIPv6'] = 'AsIs'
    tcpMptcp: bool = False
    v6only: bool = False


class KCPOptions(StrictModel):
    mtu: int = Field(default=1350, ge=576, le=1460)
    tti: int = Field(default=50, ge=10, le=5000)
    uplinkCapacity: int = Field(default=5, ge=0, le=10000)
    downlinkCapacity: int = Field(default=20, ge=0, le=10000)
    congestion: bool = False
    readBufferSize: int = Field(default=2, ge=0, le=64)
    writeBufferSize: int = Field(default=2, ge=0, le=64)


class XHTTPOptions(StrictModel):
    mode: Literal['auto', 'packet-up', 'stream-up', 'stream-one', 'x-drive'] = 'auto'
    xdrive: bool = False
    noGRPCHeader: bool = False
    noSSEHeader: bool = False
    scMaxBufferedPosts: int = Field(default=30, ge=1, le=10000)


class Fallback(StrictModel):
    name: str = Field(default='', max_length=253, pattern=r'^[a-zA-Z0-9.*-]*$')
    alpn: str = Field(default='', max_length=30)
    path: str = Field(default='', max_length=255, pattern=r'^(?:/.*)?$')
    dest: int = Field(ge=1, le=65535)
    xver: Literal[0, 1, 2] = 0


class TransportMask(StrictModel):
    type: Literal['fragment', 'sudoku', 'salamander', 'noise', 'header-custom', 'header-dns', 'header-dtls', 'header-srtp', 'header-utp', 'header-wechat', 'header-wireguard', 'mkcp-original', 'mkcp-aes128gcm', 'xdns', 'xicmp']
    settings: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def size(self):
        if len(json.dumps(self.settings)) > 16384:
            raise ValueError('A transport mask cannot exceed 16 KiB.')
        if self.type in {'salamander','sudoku','mkcp-aes128gcm'} and not self.settings.get('password'):
            raise ValueError('This mask requires a password.')
        return self


class FinalMaskOptions(StrictModel):
    tcp: list[TransportMask] = Field(default_factory=list, max_length=8)
    udp: list[TransportMask] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def directions(self):
        if any(mask.type not in {'fragment','sudoku','header-custom'} for mask in self.tcp):
            raise ValueError('Unsupported TCP mask type.')
        if any(mask.type == 'fragment' for mask in self.udp):
            raise ValueError('Fragment is a TCP mask.')
        return self


class AdvancedInbound(StrictModel):
    ss_server_key: str = Field(default='', max_length=64)
    mtproto_user_id: int | None = Field(default=None, ge=1)
    mtproto_relay_port: int | None = Field(default=None, ge=1024, le=65535)
    mtproto_domain: str = Field(default='www.cloudflare.com', max_length=253, pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]+$')
    vless_decryption: str = Field(default='none', max_length=4096)
    vless_encryption: str = Field(default='none', max_length=4096)
    finalmask: FinalMaskOptions = Field(default_factory=FinalMaskOptions)
    shadowtls_handshake: str = Field(default='www.cloudflare.com', max_length=253, pattern=r'^[A-Za-z0-9.-]+$')
    shadowtls_handshake_port: int = Field(default=443, ge=1, le=65535)
    fallbacks: list[Fallback] = Field(default_factory=list, max_length=30)
    subscription_order: int = Field(default=0, ge=0, le=1000000)
    exclude_from_subscription: bool = False
    share_host: str = Field(default='', max_length=253)
    share_port: int | None = Field(default=None, ge=1, le=65535)
    proxy_protocol: bool = False
    tcp_http_obfuscation: bool = False
    disable_xtls_flow: bool = False
    sniffing: Sniffing = Field(default_factory=Sniffing)
    tls: TLSOptions = Field(default_factory=TLSOptions)
    reality: RealityOptions = Field(default_factory=RealityOptions)
    sockopt: Sockopt | None = None
    kcp: KCPOptions = Field(default_factory=KCPOptions)
    xhttp: XHTTPOptions = Field(default_factory=XHTTPOptions)

    @field_validator('share_host')
    @classmethod
    def host(cls, value):
        if not value:
            return value
        try:
            ipaddress.ip_address(value)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value) or '..' in value:
                raise ValueError('Share host must be an IP address or hostname without a port or URL.')
        return value


def options(inbound) -> AdvancedInbound:
    return AdvancedInbound.model_validate_json(inbound.extra_json) if inbound.extra_json else AdvancedInbound()


def subscription_inbounds(inbounds):
    return sorted((i for i in inbounds if not options(i).exclude_from_subscription), key=lambda i: (options(i).subscription_order, i.id or 0))


def client_sni(inbound):
    names = options(inbound).reality.serverNames if inbound.security == 'reality' else []
    return names[0] if names else inbound.sni


def client_short_id(inbound):
    ids = options(inbound).reality.shortIds
    return ids[0] if ids else inbound.reality_short_id


def client_flow(inbound):
    return None if options(inbound).disable_xtls_flow else inbound.flow


def client_port(inbound):
    return options(inbound).share_port or inbound.port


def validate_combination(inbound):
    network, security, protocol = inbound.network, inbound.security, inbound.protocol
    engine = getattr(inbound, 'engine', 'xray')
    if protocol in {'ssh','mtproto'}:
        if engine != ('ssh' if protocol == 'ssh' else 'mtg') or network != 'tcp' or security != 'none' or inbound.flow:
            raise ValueError('SSH/MTProto require their dedicated engine, RAW and no additional TLS/XTLS layer.')
    elif engine in {'ssh','mtg'}:
        raise ValueError('This protocol does not match the selected engine.')
    if protocol in {'hysteria2', 'tuic', 'shadowtls'} and engine != 'singbox':
        raise ValueError('This protocol requires the Sing-box engine.')
    if engine == 'singbox':
        if network not in {'tcp', 'ws', 'grpc', 'httpupgrade'}:
            raise ValueError('This Sing-box version does not support XHTTP/mKCP server transports.')
        if protocol in {'hysteria2', 'tuic'} and (security != 'tls' or network != 'tcp'):
            raise ValueError('QUIC protocols require TLS and use their own UDP transport; select RAW in the form.')
        if protocol == 'shadowtls' and (security != 'none' or network != 'tcp'):
            raise ValueError('ShadowTLS v3 manages its own handshake; select RAW and no additional TLS layer.')
    if security == 'reality' and (protocol != 'vless' or network not in {'tcp', 'xhttp', 'grpc'}):
        raise ValueError('Reality requires VLESS with RAW/TCP, XHTTP or gRPC.')
    if security == 'reality' and inbound.reality_short_id and not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}', inbound.reality_short_id):
        raise ValueError('Reality Short ID must contain an even number of hexadecimal characters, at most 16.')
    if inbound.flow and (protocol != 'vless' or network != 'tcp' or security == 'none'):
        raise ValueError('XTLS flow requires VLESS over RAW/TCP with TLS or Reality.')
    advanced = options(inbound)
    if advanced.tls.ech or advanced.tls.echConfig or advanced.tls.mldsa65 or advanced.reality.finalMask or advanced.reality.finalMaskConfig or advanced.xhttp.xdrive or advanced.xhttp.mode == "x-drive":
        raise ValueError("Legacy experimental flags are unsupported. Use ECH keys, Reality ML-DSA keys and the FinalMask transport tab instead.")
    if (advanced.vless_decryption != 'none' or advanced.vless_encryption != 'none'):
        if engine != 'xray' or protocol != 'vless' or advanced.fallbacks:
            raise ValueError('VLESS encryption requires an Xray VLESS inbound without fallbacks.')
        if not all(value.startswith('mlkem768x25519plus.') for value in (advanced.vless_decryption, advanced.vless_encryption)):
            raise ValueError('A matching VLESS decryption/encryption pair is required.')
    if bool(advanced.reality.mldsa65Seed) != bool(advanced.reality.mldsa65Verify):
        raise ValueError('Both ML-DSA-65 seed and verification key are required.')
    if advanced.finalmask.udp and network != 'kcp':
        raise ValueError('UDP masks require an mKCP inbound in this core integration.')
    if advanced.finalmask.tcp and network == 'kcp':
        raise ValueError('TCP masks cannot wrap mKCP.')
    if engine == 'singbox':
        if protocol == 'shadowsocks' and security != 'none':
            raise ValueError('Sing-box Shadowsocks uses AEAD-2022; use ShadowTLS for a TLS camouflage layer.')
        if advanced.fallbacks or advanced.finalmask.tcp or advanced.finalmask.udp or advanced.proxy_protocol or advanced.tcp_http_obfuscation or advanced.tls.echServerKeys or advanced.reality.mldsa65Seed:
            raise ValueError('Fallback, FinalMask and PROXY/HTTP camouflage options require the Xray engine.')
    if advanced.fallbacks and (protocol not in {'vless', 'trojan'} or network != 'tcp' or security != 'tls'):
        raise ValueError('Fallbacks require VLESS/Trojan over RAW/TCP with TLS termination.')
    if any(row.dest == inbound.port for row in advanced.fallbacks):
        raise ValueError('Fallback destination cannot loop back to its own listening port.')
    if advanced.proxy_protocol and network == 'kcp':
        raise ValueError('PROXY protocol requires a TCP-based transport.')
    if advanced.tcp_http_obfuscation and network != 'tcp':
        raise ValueError('HTTP obfuscation requires RAW/TCP.')


def apply_stream_options(inbound, stream, client=False):
    advanced = options(inbound)
    if advanced.finalmask.tcp or advanced.finalmask.udp:
        stream['finalmask'] = advanced.finalmask.model_dump()
    if inbound.network == 'kcp':
        stream['kcpSettings'] = advanced.kcp.model_dump()
    if inbound.network == 'xhttp':
        stream['xhttpSettings'].update(advanced.xhttp.model_dump())
    if inbound.network == 'tcp' and advanced.tcp_http_obfuscation:
        stream['tcpSettings'] = {'header': {'type': 'http'}}
    if not client and advanced.proxy_protocol:
        field = {'tcp': 'tcpSettings', 'ws': 'wsSettings', 'httpupgrade': 'httpupgradeSettings'}.get(inbound.network)
        if field:
            stream.setdefault(field, {})['acceptProxyProtocol'] = True
    if not client and advanced.sockopt is not None:
        stream['sockopt'] = advanced.sockopt.model_dump()
    if not client and advanced.proxy_protocol:
        stream.setdefault('sockopt', {})['acceptProxyProtocol'] = True
    if inbound.security == 'tls':
        tls = advanced.tls.model_dump(exclude={'ech', 'echConfig', 'mldsa65', 'echServerKeys', 'echConfigList'})
        if client and advanced.tls.echConfigList:
            tls['echConfigList'] = advanced.tls.echConfigList
        if not client and advanced.tls.echServerKeys:
            tls['echServerKeys'] = advanced.tls.echServerKeys
        if client:
            tls = {k: v for k, v in tls.items() if k not in {'rejectUnknownSni', 'disableSystemRoot', 'enableSessionResumption'}}
        stream.setdefault('tlsSettings', {}).update(tls)
    if inbound.security == 'reality':
        reality = stream['realitySettings']
        if client:
            reality['spiderX'] = advanced.reality.spiderX
            if advanced.reality.mldsa65Verify:
                reality['mldsa65Verify'] = advanced.reality.mldsa65Verify
            if advanced.reality.serverNames:
                reality['serverName'] = advanced.reality.serverNames[0]
            if advanced.reality.shortIds:
                reality['shortId'] = advanced.reality.shortIds[0]
        else:
            values = advanced.reality.model_dump(exclude={'spiderX', 'serverNames', 'shortIds', 'mldsa65Verify', 'finalMask', 'finalMaskConfig'})

            reality.update(values)
            if advanced.reality.serverNames:
                reality['serverNames'] = advanced.reality.serverNames
            if advanced.reality.shortIds:
                reality['shortIds'] = advanced.reality.shortIds
