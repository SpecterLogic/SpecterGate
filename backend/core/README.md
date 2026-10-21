# Managed Xray session control

`build.sh OUTPUT` builds Xray v26.3.27 at upstream commit
`d2758a023cd7f4174a5a5fa4ff66e487d4342ba0` and applies the additive extension.
Upstream source and licenses remain in the build checkout; no upstream binary
or source archive is committed here. The source patch fails on unexpected anchors.

The dispatcher tracks authenticated **logical flows**, not OS sockets. Each flow
has a child cancellation context. Configure atomically replaces limits and
temporary blocks, then interrupts only matching links outside the registry lock.
Normal context completion releases slots. Existing oldest IPs retain their slots
when limits decrease; new excess IPs are rejected during admission. No client is
admitted before the first policy configuration. An IP can represent multiple
devices behind NAT. Remote stock cores and native WireGuard/AWG are outside this
registry.

The existing StatsService registers the additional loopback gRPC service
`spectergate.control.SessionService`. `Snapshot` and `Configure` use protobuf
Struct messages with protocol version 1. This API must never be exposed publicly.
The panel retains administrator permission and user-scope checks. Manual blocks
are persisted in the database for ten minutes and replayed after core restarts.
Legacy binaries return UNIMPLEMENTED; the panel never falls back to a core restart.

Build prerequisites: Linux amd64/arm64, Git, Python 3 and a C compiler. A suitable
installed Go is used, otherwise Go 1.26.8 is downloaded from the official HTTPS
catalog and its archive SHA-256 is verified. Go modules use checksum verification.
Registry tests run with Go's race detector before building. The backend native
tests additionally check real VLESS flows, shared-IP user isolation, limits,
slot release, RAW/WS multiplexing and XHTTP. Set `XRAY_TEST_BINARY` to the managed
binary and `XRAY_LOCATION_ASSET` to the directory containing geoip/geosite data.

Changing inbounds, credentials, certificates or upgrading the binary can still
restart the core. This extension removes restarts specifically for session
disconnection and concurrent-IP policy changes.
