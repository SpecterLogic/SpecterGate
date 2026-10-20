# Server installation

Use a dedicated Debian/Ubuntu server with systemd, Python 3.11+, and a domain pointing to its public IP. Allow TCP 80/443 for certificate issuance and the panel. Open the separate inbound TCP/UDP ports that your clients use. Installation builds the frontend locally and requires internet access to GitHub, npm and PyPI.

## Quick setup

SQLite (default):

```bash
curl -fsSLo /tmp/spectergate-install.sh https://raw.githubusercontent.com/SpecterLogic/SpecterGate/main/install.sh && sudo bash /tmp/spectergate-install.sh --domain panel.example.com
```

PostgreSQL (creates a local database with a random password):

```bash
curl -fsSLo /tmp/spectergate-install.sh https://raw.githubusercontent.com/SpecterLogic/SpecterGate/main/install.sh && sudo bash /tmp/spectergate-install.sh --domain panel.example.com --database postgresql
```

Replace `panel.example.com` with your domain. Add `--version TAG_OR_COMMIT` to select an existing release tag or commit instead of `main`. You can download and inspect the script before running it. SQLite and PostgreSQL are the supported choices; MySQL, MariaDB and TimescaleDB installation presets are not provided.

The installer creates a random owner username/password and JWT secret, installs a pinned Xray binary with SHA-256 verification, obtains a Let's Encrypt certificate and starts the service under a dedicated account. Credentials are displayed once during a fresh installation; store them securely. The account is created automatically on first startup; there is no public registration or temporary owner setup key endpoint.

Files:

- Application: `/opt/spectergate`
- Configuration: `/opt/spectergate/backend/.env` (mode 0600)
- SQLite data and integration encryption key: `/opt/spectergate/backend/data`
- PostgreSQL data: managed by the distribution PostgreSQL service
- Frontend: `/var/www/spectergate`
- Panel: `https://panel.example.com/`

```bash
spectergate status
spectergate logs              # Ctrl+C stops following logs
sudo spectergate restart
sudo spectergate stop
sudo spectergate start
```

The installer preserves existing `.env` and data on reruns. It does not migrate an existing installation between database engines. Back up before replacing the application version. A working TLS certificate is required before public login. Certificate renewal is managed by the distribution Certbot timer; check it with `systemctl list-timers`.

If Xray has an applied configuration, it is restored automatically after service restarts and unexpected core exits. Stopping Xray from the panel persists the stopped state until it is explicitly restarted/applied again. Startup applies a freshly validated configuration from the database, so account quota/expiry changes are retained.

For a deployment behind a trusted TLS passthrough/SNI proxy, bind the core to loopback, enable PROXY protocol for the corresponding TCP transports, and set the inbound's public share port separately from its internal listen port. Preserve the original client address at both the frontend proxy and core. Certificate files must be readable by the service account, with renewal hooks updating protected copies and restarting the managed core.

For development without a domain, run the backend on loopback and use SSH forwarding (`ssh -L 8000:localhost:8000 user@server`). Set the local subscription URL and disable Secure cookies only for that local HTTP test. The production installer requires a domain and HTTPS.

## Bot and encrypted backups

Each owner creates their own bot with Telegram's BotFather and enters its token in **Bot and backups**. The panel has no shared bot token. Set the owner's numeric Telegram user ID, a separate backup password (at least 16 characters), and explicitly bind any administrators allowed to create users. Every authorized person must start a private conversation with the bot.

Commands:

```text
/new username days GiB [plan_id]
/sub username
/backup
```

User creation uses the same permissions, quotas, plan and credit checks as the panel. `/backup` is owner-only. Scheduled backups are encrypted before being sent and always addressed to the configured owner. The token and backup password are stored encrypted with the installation key and are not returned by the settings API. No sales or payment commands are included.

To create or decrypt a backup locally (password is requested in the terminal):

```bash
sudo spectergate backup /root/panel.sgbackup
sudo spectergate decrypt-backup /root/panel.sgbackup /root/panel.tar.gz
```

The archive contains a consistent SQLite snapshot or PostgreSQL custom dump, a manifest, the integration master key and the generated local Xray configuration if present. It does **not** include `.env`, external certificate files, remote node disks or the operating system. Preserve those separately. Keep the backup password outside the panel; losing it makes the encrypted archive unrecoverable. Delivery is limited to 48 MiB.

Decryption writes an archive and never extracts or overwrites files automatically. Restore while the panel is stopped: inspect the archive, restore the database and `secrets.key`, retain a valid server `.env`, fix ownership to `spectergate`, and then start the service. Use PostgreSQL's `pg_restore` for a PostgreSQL dump. Test recovery on an isolated installation before relying on backups.

## Routing and connection resilience

**Routing and WARP** configures a separate policy for the local server or each remote node. Supply valid WireGuard/WARP account credentials (private key, peer public key, endpoint, assigned addresses and reserved bytes). SpecterGate does not register WARP accounts automatically. Select Direct or WARP by default and add ordered Direct/WARP/Block rules for domains, IP networks or inbounds. Conditions in one rule are combined by Xray; create separate rules when you need alternatives.

The API and private-address blocking rules precede custom rules. Private WARP keys are encrypted in storage and redacted from the admin configuration preview; node agents receive the real configuration through their authenticated channel. These are outbound routes, not an AmneziaWG inbound server.

VLESS XHTTP with TLS/Reality, alternate nodes and transports, and DNS tunnel profiles provide connection choices. Configure client-compatible transports, certificate files, SNI and the appropriate server firewall/DNS settings. Filtering behavior depends on the operator, IP, domain and client; no transport or panel guarantees permanent connectivity. Generated configurations are checked with Xray; actual reachability must be tested on the networks you intend to serve.

AmneziaWG and OpenVPN server provisioning are not implemented in this release. DNS server/router deployment and records still require the steps shown in the tunnel screen.
