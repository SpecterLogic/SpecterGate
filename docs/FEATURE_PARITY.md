# Feature coverage

This checklist tracks functional coverage against the requested 3x-ui, PasarGuard and Hiddify workflows and the supplied screenshots. It is not a claim of complete compatibility with every feature or third-party fork. A visible form alone does not count as implemented functionality.

## Implemented

| Area | Coverage | Verification / limits |
| --- | --- | --- |
| Users and groups | Time and traffic quotas, shared groups, independent subscription tokens, resource access policies | API tests; local browser workflows |
| Administration | Owner, administrator hierarchy, scopes, permissions, plan quotas and credits | Permissions and privilege-boundary tests; no automatic sales |
| Xray protocols | VLESS, VMess, Trojan, Shadowsocks | Server and exported client configurations checked with pinned Xray |
| Transports | RAW/TCP, WebSocket, gRPC, HTTPUpgrade, XHTTP, mKCP | mKCP uses Xray JSON; old mKCP header/seed presets are not supported by the pinned core |
| Security | TLS and VLESS Reality on compatible transports | Real certificates used in TLS configuration tests; Reality native configuration tests |
| TLS controls | SNI, ALPN, fingerprint in client profiles, TLS 1.2/1.3 bounds, cipher suites, curves, reject unknown SNI, system root and session resumption controls | Certificate/key file paths; no managed certificate issuer or inline key uploader yet |
| Reality controls | Target, matching X25519 key pair, multiple server names and Short IDs, client version bounds, time difference, SpiderX, xver, upload/download fallback limits | First configured server name/Short ID exported to clients; private keys masked in configuration preview |
| Stream controls | PROXY protocol for RAW/WS/HTTPUpgrade, RAW HTTP obfuscation, XHTTP modes and header switches, mKCP capacity/buffer/MTU/TTI | PROXY protocol requires a trusted upstream; HTTP obfuscation and mKCP require Xray JSON export |
| Sniffing | Enable, route-only, metadata-only, destination protocols and excluded domains | Written into generated server configuration |
| Socket options | Fast Open, keepalive, timeout, congestion algorithm, interface, DNS strategy, MPTCP and IPv6-only | Server-side settings; actual OS support and privileges vary |
| Subscription presentation | Per-inbound order, exclude from subscriptions, share-host override | Applied to individual/group exports; excluding an inbound does not disable its server accounts |
| Subscriptions | Raw/Base64 links, Xray JSON, Clash Meta, Sing-box, Outline and DNS links, client QR | Only representable combinations are exported; XHTTP/mKCP omitted from incompatible formats |
| Routing | Per-node Direct/WARP/Block/IPv4, default outbound, domain strategy, block/direct IP and domain lists, IPv4 domain lists, BitTorrent block, ordered rules by inbound/domain/IP/network/port/protocol | Core API and private-IP protection stay ahead of custom rules; geo rules need corresponding node geodata |
| WARP | WireGuard outbound with write-only encrypted account credentials | Account registration is external; native config validation is not proof of live connectivity |
| Nodes | Local and authenticated pull-based remote nodes, per-node configuration, usage receipt deduplication | Remote installation and port/firewall configuration still required |
| DNS tunnels | DNSTT/NoizDNS profiles, multiplexer configuration and authenticated metered SOCKS gateway | DNS tunnel server/router and A/NS records require deployment |
| Telegram | Installation-specific bot, bound administrators, create user by days/GiB, subscription link and QR | Private chats only; same panel quotas/scopes apply |
| Backups | Encrypted snapshots, owner-only delivery, local download/decrypt CLI | Separate backup password; external TLS certificates and remote disks need separate backup |
| Date display | Configurable IANA time zone and Persian/Gregorian calendar in authenticated panel | Database timestamps remain UTC; duration-based jobs are elapsed-time jobs, not calendar schedules |
| Security and deployment | HTTPS installer, random owner credentials, session revocation, cookie/origin/host protection, body limits, encrypted integration secrets, audit log | Not a comprehensive security audit or guarantee of filtering resistance |

## Still required for complete requested coverage

| Feature | Current status |
| --- | --- |
| Native WireGuard and AmneziaWG inbound servers | Not implemented; WARP outbound is a separate capability |
| OpenVPN server and client profiles | Not implemented |
| Other protocol families / third-party transports including XDRIVE | Not implemented; must establish engine and client compatibility first |
| TCP/UDP FinalMask controls | Not implemented |
| ECH keys/configuration, certificate generation and rotation, OCSP controls | Not implemented |
| ML-DSA-65 Reality key management | Not implemented |
| Inline certificate/key management and extra certificate chains | Not implemented |
| Full outbound catalog, chains, pools and subscription balancers | Direct, Block, IPv4 and WARP only |
| Routing tester backed by core diagnostics | Not implemented |
| Dedicated hosts/DNS editor | Not implemented |
| Inbound aggregate quotas, expiry, scheduled traffic reset and bulk operations | Not implemented; user/group quotas are available |
| Live per-inbound speed/client session counts | Aggregate traffic only; no claimed live-session/device enforcement |
| LDAP, external authentication, MFA | Local authentication only |
| Email / Discord integration and additional notifications | Not implemented; Telegram scope remains administration and owner backups |
| Private dashboard URL | Dedicated HTTPS port and random path implemented; authentication remains required |
| Custom subscription paths and a restart/update management UI | Not implemented; service CLI is available |
| Complete Linux runtime validation | Still requires clean Ubuntu/Debian installation, PostgreSQL backup/restore, real clients and representative networks |

## Compatibility references

- [Xray pinned source](https://github.com/XTLS/Xray-core/tree/v26.3.27/infra/conf)
- [3x-ui](https://github.com/MHSanaei/3x-ui)
- [PasarGuard](https://github.com/PasarGuard/panel)
- [Hiddify Manager](https://github.com/hiddify/Hiddify-Manager)

Screenshots may contain settings from different releases or forks. Engine support must be checked against the version shipped by SpecterGate; unsupported controls must not be advertised as working features.
